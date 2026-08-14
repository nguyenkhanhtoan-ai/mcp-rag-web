# Deploy MCP RAG Server lên Cloud (Railway + Postgres/pgvector)

Kiến trúc: server MCP (HTTP) + Postgres (pgvector) làm vector store, cả 2
chạy trên Railway trong cùng 1 project.

> **Lưu ý bảo mật**: server hiện **không có xác thực** — bất kỳ ai có URL
> đều gọi được tool. Phù hợp test/nội bộ tin cậy. Cần dùng thật cho doanh
> nghiệp thì nhắn mình để thêm lớp xác thực.

## Kiến trúc

```
[Claude Desktop / claude.ai / mobile] --HTTPS--> [Railway: rag-pdf service]
                                                        |
                                                  DATABASE_URL
                                                        |
                                              [Railway: Postgres + pgvector]
```

## 1. Tạo Postgres trên Railway

1. Vào project Railway hiện tại (nơi đã có service `rag-pdf`).
2. **New** → **Database** → **Add PostgreSQL**.
3. Railway tự tạo biến `DATABASE_URL` (internal) cho service Postgres này.

## 2. Nối `DATABASE_URL` vào service `rag-pdf`

1. Vào service **rag-pdf** → tab **Variables**.
2. **Add Variable Reference** → chọn service Postgres vừa tạo → chọn
   `DATABASE_URL`. Railway sẽ tự động inject đúng connection string nội bộ
   (dùng network riêng giữa các service trong project, nhanh và không tốn
   phí egress).
3. Cũng cần `OPENAI_API_KEY` như bình thường (Variables → thêm thủ công).

## 3. Bật extension pgvector

Ảnh Postgres của Railway dùng image chuẩn có sẵn pgvector, chỉ cần bật
extension — `server.py` đã tự làm việc này lúc khởi động (`vector_store.init_db()`
gọi `CREATE EXTENSION IF NOT EXISTS vector;`), **không cần làm gì thêm**.

Nếu muốn tự kiểm tra thủ công: vào tab **Data** của Postgres service trên
Railway (hoặc dùng `railway connect Postgres`), chạy:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## 4. Push code

Đảm bảo `requirements.txt`, `Dockerfile`, `vector_store.py`, `ingest.py`,
`server.py` đã ở bản dùng Postgres (đã cập nhật trong project này).

```bash
git add .
git commit -m "Switch to Postgres/pgvector"
git push origin main
```

Railway tự build lại service `rag-pdf`.

## 5. Lấy public URL cho MCP server

**Settings → Networking** (của service `rag-pdf`, không phải Postgres) →
**Generate Domain**.

MCP endpoint: `https://<domain-của-bạn>.up.railway.app/mcp`

## 6. Ingest dữ liệu

Vì Postgres là service riêng, **không ingest lúc build** được nữa — ingest
sau khi deploy, bằng Railway CLI chạy từ máy bạn (kết nối vào network nội
bộ của project):

```bash
npm install -g @railway/cli
railway login
railway link              # chọn đúng project
railway run python ingest.py
```

`railway run` chạy `ingest.py` **trên máy bạn** nhưng với các biến môi
trường của Railway (bao gồm `DATABASE_URL` nội bộ) — nên cần đảm bảo
`documents/` trên máy bạn có PDF thật, và local đã cài đủ
`pip install -r requirements.txt`.

Chạy lại bất cứ khi nào thêm/sửa PDF — script tự bỏ qua file không đổi:

```bash
railway run python ingest.py
```

## 7. Kết nối từ Claude (Desktop / claude.ai / mobile)

Add qua UI, **không sửa `claude_desktop_config.json`**:

1. Claude → **Settings → Connectors** → **Add custom connector** → **Web**.
2. Paste URL: `https://<domain-của-bạn>.up.railway.app/mcp`
3. **Add** → **Connect**.

## 8. Kiểm tra

```bash
curl https://<domain-của-bạn>.up.railway.app/health
# → ok
```

## Vì sao chuyển sang Postgres thay vì ChromaDB

- **Quản lý tập trung**: 1 database, dễ backup/restore, dễ audit, phù hợp
  khi công ty đã có hạ tầng Postgres sẵn.
- **Không cần Persistent Volume riêng** cho vector data — Postgres tự quản
  lý durability.
- **Ingest tăng dần dễ hơn**: không cần rebuild Docker image mỗi lần thêm
  PDF (khác với cách ingest-lúc-build trước đây).
- **Truy vấn SQL trực tiếp** khi cần debug hoặc phân tích dữ liệu ngoài
  phạm vi RAG (ví dụ: đếm chunk theo file, tìm file chưa ingest...).

## Giới hạn / điều cần biết

- Index dùng **HNSW** (approximate nearest neighbor) — đủ nhanh và chính
  xác cho tới hàng trăm nghìn~triệu vector, không cần đổi gì thêm ở quy mô
  vài trăm-nghìn PDF.
- `EMBEDDING_DIM = 1536` trong `config.py` phải khớp với model embedding
  đang dùng (`text-embedding-3-small`). Nếu đổi model embedding có số
  chiều khác, cần `ALTER TABLE` lại cột `embedding` hoặc tạo bảng mới.
- Chi phí Postgres trên Railway tính theo usage (RAM/CPU/storage) — với
  vài trăm-nghìn PDF, storage cho vector nhỏ, chi phí không đáng kể so với
  service chạy 24/7.

---

# Deploy Web App quản lý upload (nhiều người dùng, phân quyền)

Service thứ 2, riêng biệt với MCP server, cho phép nhiều người **đăng nhập
bằng email/password** để upload/xoá PDF theo phân quyền (admin/uploader/
viewer, theo phòng ban). Dùng **chung 1 Postgres** với MCP server ở trên —
tài liệu upload qua web app sẽ tự động xuất hiện khi `search_docs` được gọi.

## Kiến trúc đầy đủ

```
[Người dùng - trình duyệt] --login--> [Railway: rag-pdf-webapp service]
                                              |
                                        DATABASE_URL (chung)
                                              |
[Claude] --HTTPS--> [Railway: rag-pdf service (MCP)] --> [Railway: Postgres + pgvector]
```

## 1. Tạo service mới trên Railway (cùng project với `rag-pdf` và Postgres)

1. Trong project Railway hiện tại → **New** → **GitHub Repo** → chọn cùng
   repo `mcp-rag` (monorepo, dùng chung code với MCP server).
2. Đặt tên service, ví dụ `rag-pdf-webapp`.

## 2. Cấu hình Dockerfile Path

Vì `webapp/Dockerfile` cần build context là **thư mục gốc repo** (để lấy
được `config.py`, `pdf_utils.py`, `vector_store.py` dùng chung):

**Settings → Build** → **Dockerfile Path**: `webapp/Dockerfile`
**Root Directory**: để trống (mặc định = gốc repo)

## 3. Biến môi trường

**Settings → Variables**:

| Key | Value |
|---|---|
| `DATABASE_URL` | **Add Variable Reference** → chọn Postgres service (giống MCP server) |
| `OPENAI_API_KEY` | `sk-...` (giống MCP server) |
| `SESSION_SECRET` | chuỗi ngẫu nhiên dài — tạo bằng `python -c "import secrets; print(secrets.token_hex(32))"` |

## 4. Lấy public URL

**Settings → Networking** → **Generate Domain**.

Domain dạng: `https://rag-pdf-webapp-production-xxxx.up.railway.app`

## 5. Tạo tài khoản admin đầu tiên

Sau khi service deploy xong (build thành công), chạy từ máy bạn qua
Railway CLI:

```bash
railway link              # chọn đúng project, chọn service rag-pdf-webapp
railway run python webapp/init_admin.py --email admin@company.com --password "matkhaumanh123" --name "Admin"
```

## 6. Đăng nhập và dùng

Truy cập `https://rag-pdf-webapp-production-xxxx.up.railway.app/login`,
đăng nhập bằng tài khoản admin vừa tạo. Từ đây:

- **Admin** tạo phòng ban (Settings → Phòng ban) và tạo user cho từng
  phòng ban (Quản lý user), gán vai trò `uploader`/`viewer`.
- **Uploader** đăng nhập, upload PDF — hệ thống tự chunk, embed (gọi
  OpenAI), lưu vào Postgres. Trạng thái hiển thị trực tiếp trên dashboard:
  `pending` → `ingesting` → `ingested`/`failed`.
- Tài liệu ingest qua web app **ngay lập tức** khả dụng cho `search_docs`
  bên MCP server (dùng chung Postgres).

## Quan hệ với `ingest.py` (CLI)

`ingest.py` (ở thư mục gốc) vẫn hoạt động bình thường — dùng tốt cho
dev/test local hoặc ingest hàng loạt ban đầu từ thư mục `documents/`. Tài
liệu ingest qua CLI sẽ có `document_id = NULL` (không gắn phòng ban/người
upload), vẫn search được bình thường nhưng không quản lý được qua web app
(không hiện trong danh sách, không xoá được qua UI — cần dùng
`python ingest.py --reset` hoặc SQL trực tiếp nếu muốn dọn).

Khuyến nghị: dùng **web app làm kênh chính** để nhiều người cùng đóng góp
tài liệu có kiểm soát; `ingest.py` CLI chỉ dùng cho admin/dev khi cần nạp
nhanh số lượng lớn lúc setup ban đầu.

## Giới hạn hiện tại (Giai đoạn 1)

- **Phân quyền mới áp dụng ở mức upload/xoá**, chưa áp dụng ở mức
  `search_docs` — khi Claude gọi `search_docs`, kết quả trả về từ **toàn
  bộ** kho tài liệu, không lọc theo phòng ban của người hỏi (vì MCP server
  hiện chưa biết "ai đang hỏi" — cần thêm OAuth2, đây là Giai đoạn 2).
- File PDF lưu trực tiếp trong Postgres (`BYTEA`) — đơn giản hoá vận hành,
  phù hợp tới vài trăm-nghìn file cỡ vừa. Nếu sau này cần hàng chục nghìn
  file hoặc file rất lớn, nên chuyển sang lưu trên S3/object storage và
  chỉ giữ metadata trong Postgres.
- Session dùng cookie ký đơn giản (không phải JWT/OAuth) — đủ dùng nội bộ,
  nhưng không có refresh token, single sign-out (đổi `SESSION_SECRET` sẽ
  logout toàn bộ user đang đăng nhập).
