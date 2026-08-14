"""
Script ingest thủ công.

Cách dùng:
    python ingest.py                # ingest tất cả PDF mới/đã đổi trong documents/
    python ingest.py --reset        # xoá index cũ, ingest lại từ đầu
    python ingest.py --dir /path    # chỉ định thư mục PDF khác

Chạy lại an toàn nhiều lần: file đã ingest (theo hash nội dung) sẽ được bỏ qua,
trừ khi dùng --reset hoặc --force.
"""
import argparse
import hashlib
import sys
from pathlib import Path

from config import DOCUMENTS_DIR, EMBEDDING_BATCH_SIZE
from pdf_utils import process_pdf
import vector_store


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def ingest_file(pdf_path: Path, force: bool = False) -> int:
    content_hash = file_hash(pdf_path)

    if not force and vector_store.already_ingested(pdf_path.name, content_hash):
        print(f"  [skip] {pdf_path.name} (không đổi)")
        return 0

    # Nếu file từng ingest (cùng tên, nội dung khác hoặc force) -> xoá bản cũ trước
    vector_store.delete_by_source(pdf_path.name)

    chunks = process_pdf(pdf_path)
    if not chunks:
        print(f"  [warn] {pdf_path.name}: không trích được text (có thể là PDF scan?)")
        return 0

    total = 0
    for i in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[i : i + EMBEDDING_BATCH_SIZE]
        embeddings = vector_store.embed_texts([c.text for c in batch])

        rows = [
            {
                "id": f"{pdf_path.name}::p{c.page}::c{c.chunk_index}::{content_hash}",
                "source": c.source,
                "page": c.page,
                "chunk_index": c.chunk_index,
                "content_hash": content_hash,
                "document": c.text,
                "embedding": emb,
            }
            for c, emb in zip(batch, embeddings)
        ]
        vector_store.add_chunks(rows)
        total += len(batch)

    print(f"  [ok] {pdf_path.name}: {total} chunks")
    return total


def main():
    parser = argparse.ArgumentParser(description="Ingest PDF vào Postgres (pgvector)")
    parser.add_argument("--dir", type=str, default=None, help="Thư mục chứa PDF (mặc định: documents/)")
    parser.add_argument("--reset", action="store_true", help="Xoá toàn bộ index cũ trước khi ingest")
    parser.add_argument("--force", action="store_true", help="Ingest lại kể cả file không đổi")
    args = parser.parse_args()

    docs_dir = Path(args.dir) if args.dir else DOCUMENTS_DIR
    if not docs_dir.exists():
        print(f"Không tìm thấy thư mục: {docs_dir}", file=sys.stderr)
        sys.exit(1)

    pdf_files = sorted(docs_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"Không có file .pdf nào trong {docs_dir}")
        sys.exit(0)

    vector_store.init_db()
    if args.reset:
        vector_store.reset()

    print(f"Tìm thấy {len(pdf_files)} file PDF trong {docs_dir}")
    total_chunks = 0
    for pdf_path in pdf_files:
        total_chunks += ingest_file(pdf_path, force=args.force or args.reset)

    print(f"\nHoàn tất. Tổng số chunk mới được thêm: {total_chunks}")
    print(f"Tổng số chunk hiện có trong database: {vector_store.count()}")


if __name__ == "__main__":
    main()
