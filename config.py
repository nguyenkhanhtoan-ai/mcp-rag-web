"""
Cấu hình dùng chung cho ingest.py và server.py
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Đường dẫn ---
BASE_DIR = Path(__file__).resolve().parent
DOCUMENTS_DIR = BASE_DIR / "documents"      # nơi bỏ các file PDF cần ingest

# --- Postgres (pgvector) ---
DATABASE_URL = os.environ.get("DATABASE_URL", "")
TABLE_NAME = "pdf_chunks"
EMBEDDING_DIM = 1536  # phải khớp với EMBEDDING_MODEL bên dưới

# --- OpenAI ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
EMBEDDING_MODEL = "text-embedding-3-small"  # 1536 dims, rẻ, đủ tốt cho vài trăm file
EMBEDDING_BATCH_SIZE = 100                  # số chunk gửi mỗi lần gọi OpenAI

# --- Chunking ---
CHUNK_SIZE = 800        # số token mỗi chunk (xấp xỉ)
CHUNK_OVERLAP = 150      # số token overlap giữa 2 chunk liên tiếp

# --- Search ---
DEFAULT_TOP_K = 5


def require_api_key():
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "Chưa thấy OPENAI_API_KEY. Hãy set biến môi trường, ví dụ:\n"
            "  export OPENAI_API_KEY=sk-...\n"
            "hoặc tạo file .env trong thư mục project với dòng:\n"
            "  OPENAI_API_KEY=sk-..."
        )


def require_database_url():
    if not DATABASE_URL:
        raise RuntimeError(
            "Chưa thấy DATABASE_URL. Hãy set biến môi trường, ví dụ:\n"
            "  export DATABASE_URL=postgresql://user:pass@host:5432/dbname\n"
            "hoặc tạo file .env trong thư mục project với dòng tương tự.\n"
            "Trên Railway: thêm Postgres plugin, biến này sẽ tự có sẵn."
        )
