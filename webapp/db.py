"""
Lớp truy cập database cho web app quản lý user/phòng ban/tài liệu.

Dùng chung 1 Postgres với vector_store.py (bảng pdf_chunks), thêm các bảng:
- departments: danh sách phòng ban
- users: tài khoản đăng nhập (email/password), gắn với 1 phòng ban + vai trò
- documents: metadata + nội dung PDF (lưu trực tiếp trong Postgres dạng BYTEA)
- audit_log: lịch sử upload/xoá/ingest
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import bcrypt
import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DATABASE_URL, require_database_url  # noqa: E402

ROLES = ("admin", "uploader", "viewer")
DOC_STATUSES = ("pending", "ingesting", "ingested", "failed")


def get_connection():
    require_database_url()
    return psycopg2.connect(DATABASE_URL)


def init_admin_db():
    """Tạo các bảng users/departments/documents/audit_log nếu chưa có."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS departments (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'viewer',
                    department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id SERIAL PRIMARY KEY,
                    filename TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    file_data BYTEA NOT NULL,
                    department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
                    uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    ingested_at TIMESTAMPTZ
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS documents_department_idx ON documents (department_id);
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    action TEXT NOT NULL,
                    document_id INTEGER,
                    detail TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
        conn.commit()
    finally:
        conn.close()


# ---------- Password ----------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# ---------- Departments ----------

def list_departments() -> list[dict]:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM departments ORDER BY name;")
            return cur.fetchall()
    finally:
        conn.close()


def create_department(name: str) -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO departments (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id;",
                (name,),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute("SELECT id FROM departments WHERE name = %s;", (name,))
                row = cur.fetchone()
        conn.commit()
        return row[0]
    finally:
        conn.close()


# ---------- Users ----------

def get_user_by_email(email: str) -> Optional[dict]:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE email = %s;", (email.lower().strip(),))
            return cur.fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s;", (user_id,))
            return cur.fetchone()
    finally:
        conn.close()


def list_users() -> list[dict]:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT u.*, d.name AS department_name
                FROM users u LEFT JOIN departments d ON u.department_id = d.id
                ORDER BY u.created_at;
            """)
            return cur.fetchall()
    finally:
        conn.close()


def create_user(email: str, password: str, name: str, role: str, department_id: Optional[int]) -> int:
    if role not in ROLES:
        raise ValueError(f"role phải là 1 trong {ROLES}")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (email, password_hash, name, role, department_id)
                VALUES (%s, %s, %s, %s, %s) RETURNING id;
                """,
                (email.lower().strip(), hash_password(password), name, role, department_id),
            )
            user_id = cur.fetchone()[0]
        conn.commit()
        return user_id
    finally:
        conn.close()


def update_user(user_id: int, role: Optional[str] = None, department_id=None,
                 is_active: Optional[bool] = None, _dept_unset=object()):
    """Cập nhật role/department_id/is_active. department_id=None nghĩa là bỏ
    phòng ban (set NULL); dùng _dept_unset (mặc định) để giữ nguyên."""
    fields, values = [], []
    if role is not None:
        if role not in ROLES:
            raise ValueError(f"role phải là 1 trong {ROLES}")
        fields.append("role = %s")
        values.append(role)
    if department_id is not _dept_unset:
        fields.append("department_id = %s")
        values.append(department_id)
    if is_active is not None:
        fields.append("is_active = %s")
        values.append(is_active)
    if not fields:
        return
    values.append(user_id)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = %s;", values)
        conn.commit()
    finally:
        conn.close()


def count_admins(exclude_user_id: Optional[int] = None) -> int:
    """Đếm số admin đang active - dùng để chặn tự hạ quyền/khoá admin cuối cùng."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if exclude_user_id is not None:
                cur.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = TRUE AND id != %s;",
                    (exclude_user_id,),
                )
            else:
                cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = TRUE;")
            return cur.fetchone()[0]
    finally:
        conn.close()


# ---------- Documents ----------

def create_document(filename: str, content_hash: str, file_data: bytes,
                     department_id: Optional[int], uploaded_by: int) -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (filename, content_hash, file_data, department_id, uploaded_by, status)
                VALUES (%s, %s, %s, %s, %s, 'pending') RETURNING id;
                """,
                (filename, content_hash, psycopg2.Binary(file_data), department_id, uploaded_by),
            )
            doc_id = cur.fetchone()[0]
        conn.commit()
        return doc_id
    finally:
        conn.close()


def get_document(document_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM documents WHERE id = %s;", (document_id,))
            return cur.fetchone()
    finally:
        conn.close()


def get_document_file(document_id: int) -> Optional[bytes]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT file_data FROM documents WHERE id = %s;", (document_id,))
            row = cur.fetchone()
            return bytes(row[0]) if row else None
    finally:
        conn.close()


def list_documents(department_id: Optional[int] = None) -> list[dict]:
    """department_id=None (và caller là admin) -> trả về tất cả. Nếu muốn lọc
    theo 1 phòng ban cụ thể thì truyền id vào."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if department_id is not None:
                cur.execute("""
                    SELECT doc.id, doc.filename, doc.status, doc.error_message,
                           doc.chunk_count, doc.uploaded_at, doc.ingested_at,
                           doc.department_id, d.name AS department_name,
                           u.name AS uploaded_by_name
                    FROM documents doc
                    LEFT JOIN departments d ON doc.department_id = d.id
                    LEFT JOIN users u ON doc.uploaded_by = u.id
                    WHERE doc.department_id = %s
                    ORDER BY doc.uploaded_at DESC;
                """, (department_id,))
            else:
                cur.execute("""
                    SELECT doc.id, doc.filename, doc.status, doc.error_message,
                           doc.chunk_count, doc.uploaded_at, doc.ingested_at,
                           doc.department_id, d.name AS department_name,
                           u.name AS uploaded_by_name
                    FROM documents doc
                    LEFT JOIN departments d ON doc.department_id = d.id
                    LEFT JOIN users u ON doc.uploaded_by = u.id
                    ORDER BY doc.uploaded_at DESC;
                """)
            return cur.fetchall()
    finally:
        conn.close()


def update_document_status(document_id: int, status: str, chunk_count: Optional[int] = None,
                            error_message: Optional[str] = None):
    if status not in DOC_STATUSES:
        raise ValueError(f"status phải là 1 trong {DOC_STATUSES}")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            ingested_at = datetime.now(timezone.utc) if status == "ingested" else None
            cur.execute(
                """
                UPDATE documents
                SET status = %s,
                    chunk_count = COALESCE(%s, chunk_count),
                    error_message = %s,
                    ingested_at = COALESCE(%s, ingested_at)
                WHERE id = %s;
                """,
                (status, chunk_count, error_message, ingested_at, document_id),
            )
        conn.commit()
    finally:
        conn.close()


def delete_document(document_id: int):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s;", (document_id,))
        conn.commit()
    finally:
        conn.close()


# ---------- Audit log ----------

def add_audit_log(user_id: Optional[int], action: str, document_id: Optional[int] = None,
                   detail: Optional[str] = None):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log (user_id, action, document_id, detail) VALUES (%s, %s, %s, %s);",
                (user_id, action, document_id, detail),
            )
        conn.commit()
    finally:
        conn.close()


def list_audit_log(limit: int = 200) -> list[dict]:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT a.*, u.name AS user_name, u.email AS user_email
                FROM audit_log a LEFT JOIN users u ON a.user_id = u.id
                ORDER BY a.created_at DESC LIMIT %s;
            """, (limit,))
            return cur.fetchall()
    finally:
        conn.close()
