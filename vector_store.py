"""
Wrapper quanh Postgres (pgvector) + OpenAI embeddings.

Thay thế ChromaDB: dữ liệu lưu trong 1 bảng Postgres, index bằng pgvector
(HNSW), phù hợp khi cần 1 database quản lý tập trung, nhiều người/service
cùng truy cập, hoặc khi công ty đã có sẵn hạ tầng Postgres.
"""
from typing import Sequence

import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
from openai import OpenAI

from config import (
    DATABASE_URL,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    OPENAI_API_KEY,
    TABLE_NAME,
    require_api_key,
    require_database_url,
)

_openai_client: OpenAI | None = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        require_api_key()
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Gọi OpenAI embedding API cho một batch text."""
    client = _get_openai_client()
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=list(texts))
    return [item.embedding for item in resp.data]


def get_connection(register_vector_type: bool = True):
    """Mở 1 connection Postgres mới, mặc định đã đăng ký kiểu vector.

    register_vector_type=False dùng khi extension `vector` có thể CHƯA tồn
    tại (ví dụ Postgres hoàn toàn mới) - register_vector() sẽ lỗi nếu gọi
    trước khi CREATE EXTENSION chạy xong. init_db() dùng cờ này để tự tạo
    extension trước, tránh vòng lặp con-gà-quả-trứng.
    """
    require_database_url()
    conn = psycopg2.connect(DATABASE_URL)
    if register_vector_type:
        register_vector(conn)
    return conn


def init_db():
    """Tạo extension pgvector, bảng, và index nếu chưa có. Gọi 1 lần lúc start."""
    # Bước 1: tạo extension bằng connection KHÔNG đăng ký kiểu vector
    # (vì extension có thể chưa tồn tại, register_vector sẽ lỗi nếu gọi sớm).
    conn = get_connection(register_vector_type=False)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.commit()
    finally:
        conn.close()

    # Bước 2: giờ extension đã chắc chắn tồn tại, dùng connection bình
    # thường (có đăng ký kiểu vector) để tạo bảng/index.
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    page INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    document TEXT NOT NULL,
                    embedding VECTOR({EMBEDDING_DIM}) NOT NULL
                );
            """)
            # document_id: liên kết tới bảng documents (webapp) - để trống (NULL)
            # với dữ liệu ingest qua CLI cũ, không dùng FK cứng để tránh phụ
            # thuộc thứ tự khởi tạo giữa 2 module.
            cur.execute(f"""
                ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS document_id INTEGER;
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS {TABLE_NAME}_source_idx
                ON {TABLE_NAME} (source);
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS {TABLE_NAME}_document_id_idx
                ON {TABLE_NAME} (document_id);
            """)
            # HNSW: index gần đúng cho cosine similarity, tốt cho vài chục nghìn~triệu vector
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS {TABLE_NAME}_embedding_idx
                ON {TABLE_NAME} USING hnsw (embedding vector_cosine_ops);
            """)
        conn.commit()
    finally:
        conn.close()


def count() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {TABLE_NAME};")
            return cur.fetchone()[0]
    finally:
        conn.close()


def already_ingested(source_name: str, content_hash: str) -> bool:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT 1 FROM {TABLE_NAME} WHERE source = %s AND content_hash = %s LIMIT 1;",
                (source_name, content_hash),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def delete_by_source(source_name: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE_NAME} WHERE source = %s;", (source_name,))
        conn.commit()
    finally:
        conn.close()


def delete_by_document_id(document_id: int):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {TABLE_NAME} WHERE document_id = %s;", (document_id,))
        conn.commit()
    finally:
        conn.close()


def add_chunks(rows: list[dict]):
    """
    rows: list các dict có keys: id, source, page, chunk_index, content_hash,
    document, embedding (list[float]), document_id (int | None, optional)
    """
    if not rows:
        return
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                f"""
                INSERT INTO {TABLE_NAME}
                    (id, source, page, chunk_index, content_hash, document, embedding, document_id)
                VALUES %s
                ON CONFLICT (id) DO UPDATE SET
                    document = EXCLUDED.document,
                    embedding = EXCLUDED.embedding,
                    content_hash = EXCLUDED.content_hash,
                    document_id = EXCLUDED.document_id;
                """,
                [
                    (
                        r["id"],
                        r["source"],
                        r["page"],
                        r["chunk_index"],
                        r["content_hash"],
                        r["document"],
                        r["embedding"],
                        r.get("document_id"),
                    )
                    for r in rows
                ],
                template="(%s, %s, %s, %s, %s, %s, %s::vector, %s)",
            )
        conn.commit()
    finally:
        conn.close()


def query(query_embedding: list[float], top_k: int) -> list[dict]:
    """Trả về top_k chunk gần nhất, kèm similarity (1 - cosine distance)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT document, source, page, chunk_index,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM {TABLE_NAME}
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
                """,
                (query_embedding, query_embedding, top_k),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def list_sources() -> dict[str, int]:
    """Trả về {tên_file: số_chunk} cho toàn bộ dữ liệu đã ingest."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT source, COUNT(*) FROM {TABLE_NAME} GROUP BY source ORDER BY source;")
            return {row[0]: row[1] for row in cur.fetchall()}
    finally:
        conn.close()


def reset():
    """Xoá sạch toàn bộ dữ liệu (dùng khi muốn ingest lại từ đầu)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {TABLE_NAME};")
        conn.commit()
    finally:
        conn.close()
