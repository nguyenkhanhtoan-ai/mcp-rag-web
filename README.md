# MCP RAG Server cho PDF

MCP server (HTTP) cho phép Claude tìm kiếm ngữ nghĩa (semantic search) trên
các file PDF của bạn thông qua RAG (Retrieval-Augmented Generation).

- **Transport**: HTTP (streamable-http) — kết nối qua Claude Connectors,
  dùng được trên Claude Desktop, claude.ai, và mobile
- **Vector DB**: Postgres + [pgvector](https://github.com/pgvector/pgvector)
  (index HNSW)
- **Embedding**: OpenAI `text-embedding-3-small`
- **PDF**: chỉ hỗ trợ PDF dạng text (không OCR)
- **Xác thực**: không có (xem lưu ý bảo mật trong `DEPLOY.md`)

## Cấu trúc project

```
mcp-rag-pdf/
├── documents/          # Bỏ file PDF cần index vào đây (dùng cho ingest.py CLI)
├── config.py             # Cấu hình chung
├── pdf_utils.py          # Đọc PDF + chia chunk
├── vector_store.py       # Wrapper Postgres/pgvector + OpenAI embedding
├── ingest.py             # Script CLI - nạp/refresh dữ liệu từ documents/
├── server.py              # MCP server (HTTP) - Claude gọi search_docs qua đây
├── Dockerfile             # Build MCP server
├── requirements.txt
├── webapp/                # Web app upload PDF nhiều người dùng, phân quyền
│   ├── app.py               # FastAPI: login, dashboard, upload, admin
│   ├── db.py                 # users/departments/documents/audit_log
│   ├── auth.py                # Session + kiểm tra phân quyền
│   ├── ingest_core.py          # Logic ingest dùng chung (gọi từ web upload)
│   ├── init_admin.py            # Script tạo tài khoản admin đầu tiên
│   ├── templates/                # Giao diện HTML (login, dashboard, admin)
│   ├── Dockerfile                 # Build web app (xem lưu ý build context trong DEPLOY.md)
│   └── requirements.txt
└── DEPLOY.md              # Hướng dẫn deploy lên cloud (Railway + Postgres)
```

Có **2 cách nạp tài liệu**: `ingest.py` (CLI, đơn giản cho dev/nạp hàng loạt
ban đầu) và **web app** (`webapp/`, dành cho nhiều người dùng cùng
upload/quản lý theo phân quyền — xem chi tiết trong `DEPLOY.md`).

## 1. Cài đặt (chạy dev trên máy)

```bash
cd mcp-rag-pdf
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Cần có sẵn 1 Postgres có extension `pgvector` — dễ nhất là chạy local qua
Docker:

```bash
docker run -d --name pg-rag -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 pgvector/pgvector:pg16
```

## 2. Cấu hình biến môi trường

Tạo file `.env` (copy từ `.env.example`):

```
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
```

## 3. Ingest PDF

Bỏ file `.pdf` vào `documents/`, sau đó chạy:

```bash
python ingest.py
```

Lần chạy đầu tự tạo extension `vector`, bảng, và index HNSW nếu chưa có.

Các lệnh hữu ích khác:

```bash
python ingest.py --reset          # xoá index cũ, ingest lại từ đầu
python ingest.py --force          # ingest lại tất cả kể cả file không đổi
python ingest.py --dir /path/khac # ingest từ thư mục khác
```

Chạy lại `python ingest.py` bất cứ khi nào thêm/sửa file PDF — script tự
động bỏ qua file không đổi (dựa trên hash nội dung), chỉ re-index file mới
hoặc đã thay đổi.

**Lưu ý chi phí**: mỗi lần ingest gọi OpenAI Embedding API. Với vài trăm
file PDF, chi phí `text-embedding-3-small` thường dưới $1.

## 4. Chạy thử server local

```bash
python server.py
```

Mặc định lắng nghe tại `http://0.0.0.0:8000/mcp`, có endpoint kiểm tra
sống tại `http://localhost:8000/health`.

Đổi port bằng biến môi trường: `PORT=8080 python server.py`

Test bằng [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector):

```bash
npx @modelcontextprotocol/inspector http://localhost:8000/mcp
```

## 5. Chạy thử web app quản lý upload (local)

Web app dùng chung Postgres ở trên, chạy ở port khác:

```bash
cd webapp
pip install -r requirements.txt
export SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
python init_admin.py --email admin@company.com --password "matkhaumanh123" --name "Admin"
uvicorn app:app --reload --port 8001
```

Mở `http://localhost:8001/login`, đăng nhập bằng tài khoản admin vừa tạo.

## 6. Deploy lên cloud + kết nối vào Claude

Xem hướng dẫn chi tiết trong [`DEPLOY.md`](./DEPLOY.md) — deploy MCP
server + web app + Postgres/pgvector lên Railway, lấy public URL, rồi add
qua **Claude → Settings → Connectors → Add custom connector**.

## Quy trình cập nhật dữ liệu

Local: chạy lại `python ingest.py` sau khi thêm/sửa PDF trong `documents/`.

Cloud (Railway): ingest bằng `railway run python ingest.py` từ máy bạn —
không cần rebuild image (chi tiết trong `DEPLOY.md`).

## Giới hạn hiện tại

- Chỉ đọc PDF dạng text; PDF scan (ảnh) sẽ bị bỏ qua với cảnh báo.
- Xoá file khỏi `documents/` không tự động xoá khỏi index — cần chạy
  `python ingest.py --reset` để làm sạch hoàn toàn.
- Không có xác thực — chỉ nên deploy cho môi trường nội bộ tin cậy, hoặc
  đặt sau 1 lớp bảo vệ khác (VPN, IP allowlist...).
- Đổi model embedding (số chiều khác 1536) cần cập nhật `EMBEDDING_DIM`
  trong `config.py` và tạo lại bảng.
