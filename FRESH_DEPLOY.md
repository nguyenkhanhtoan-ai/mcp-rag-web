# Deploy hoàn toàn mới (project riêng, không liên quan tới bản trước)

Hướng dẫn này đi từ **0 đến hoàn chỉnh**: repo GitHub mới, Railway project
mới, tên hoàn toàn khác với project `mcp-rag` đã triển khai trước — 2 hệ
thống độc lập, không đụng chạm nhau.

Ví dụ dùng tên `rag-acme` xuyên suốt hướng dẫn — bạn thay bằng tên bạn
muốn (ví dụ tên công ty), nhớ đổi nhất quán ở mọi bước.

**Kết quả sau khi làm xong**: 1 Postgres + 2 service (MCP server cho
Claude, Web app cho người dùng upload) chạy trên Railway, độc lập hoàn
toàn với project cũ.

---

## Bước 0 — Chuẩn bị

- Tài khoản GitHub
- Tài khoản Railway ([railway.app](https://railway.app)), đăng nhập bằng GitHub
- OpenAI API key (sk-...)
- Máy local đã cài Python 3.12+, Git

---

## Bước 1 — Tạo repo GitHub mới

Vào [github.com/new](https://github.com/new):
- Tên repo: `rag-acme` (hoặc tên bạn chọn)
- **Không** tích "Initialize with README"
- Create repository

---

## Bước 2 — Đẩy code lên repo mới

Giải nén project đã có (file zip mình gửi), rồi:

```bash
cd mcp-rag-pdf
rm -rf .git
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<username>/rag-acme.git
git push -u origin main
```

`rm -rf .git` đảm bảo repo mới sạch, không mang theo lịch sử/remote của
project cũ.

---

## Bước 3 — Tạo Railway project mới

Vào [railway.app/new](https://railway.app/new):
- **Deploy from GitHub repo** → chọn `rag-acme`
- Đặt tên project: `rag-acme` (Settings project, góc trên)

Railway sẽ tạo 1 service đầu tiên từ repo — đây sẽ là service MCP server,
đổi tên nó cho rõ (xem Bước 5).

> **Quan trọng**: đây phải là **project Railway mới**, không phải thêm
> service vào project `mcp-rag` cũ. Kiểm tra ở góc trên cùng dashboard
> Railway, tên project phải là project mới bạn vừa tạo.

---

## Bước 4 — Thêm Postgres

Trong project `rag-acme` vừa tạo:
- **New** → **Database** → **Add PostgreSQL**
- Railway tự tạo biến `DATABASE_URL` nội bộ cho service Postgres này

---

## Bước 5 — Cấu hình service MCP server

Service đầu tiên (tạo tự động ở Bước 3) — đổi tên thành `mcp-server`:
- **Settings** → **Service Name** → `mcp-server`
- **Settings → Build**: Dockerfile Path để mặc định (= `Dockerfile` ở gốc repo) — không cần sửa
- **Variables**:
  | Key | Value |
  |---|---|
  | `DATABASE_URL` | **Add Variable Reference** → chọn service Postgres → `DATABASE_URL` |
  | `OPENAI_API_KEY` | `sk-...` |
- **Settings → Networking** → **Generate Domain**

Ghi lại domain, ví dụ: `mcp-server-production-xxxx.up.railway.app`

---

## Bước 6 — Tạo service Web app

Vẫn trong project `rag-acme`:
- **New** → **GitHub Repo** → chọn lại `rag-acme` (cùng repo, service thứ 2)
- Đặt tên: `webapp`
- **Settings → Build** → **Dockerfile Path**: `webapp/Dockerfile`
- **Settings → Build** → **Root Directory**: để trống (mặc định = gốc repo — bắt buộc, vì `webapp/Dockerfile` cần copy file ở thư mục gốc)
- **Variables**:
  | Key | Value |
  |---|---|
  | `DATABASE_URL` | **Add Variable Reference** → chọn service Postgres (giống Bước 5) |
  | `OPENAI_API_KEY` | `sk-...` (giống Bước 5) |
  | `SESSION_SECRET` | chạy `python -c "import secrets; print(secrets.token_hex(32))"` để tạo, paste vào |
- **Settings → Networking** → **Generate Domain**

Ghi lại domain, ví dụ: `webapp-production-yyyy.up.railway.app`

---

## Bước 7 — Tạo tài khoản admin đầu tiên

Cài Railway CLI trên máy local:

```bash
npm install -g @railway/cli
railway login
cd rag-acme
railway link              # chọn đúng project rag-acme, service webapp
```

Tạo admin:

```bash
railway run python webapp/init_admin.py \
  --email admin@company.com \
  --password "matkhaumanh123" \
  --name "Admin"
```

---

## Bước 8 — Đăng nhập, tạo phòng ban, tạo user

Truy cập `https://webapp-production-yyyy.up.railway.app/login`, đăng nhập
bằng tài khoản admin vừa tạo.

- **Phòng ban**: tạo các phòng ban cần thiết (Sales, HR, Kỹ thuật...)
- **Quản lý user**: tạo user cho từng người, gán vai trò (`uploader`/
  `viewer`/`admin`) và phòng ban tương ứng
- Đăng xuất, để từng người tự đăng nhập bằng tài khoản của họ và upload
  tài liệu

---

## Bước 9 — Kết nối MCP server vào Claude

Trên Claude (Desktop / claude.ai / mobile):
1. **Settings → Connectors** → **Add custom connector** → **Web**
2. URL: `https://mcp-server-production-xxxx.up.railway.app/mcp`
3. **Add** → **Connect**

Kiểm tra `search_docs` và `list_indexed_documents` xuất hiện trong tool
list, thử hỏi 1 câu liên quan tới tài liệu vừa upload.

---

## Kiểm tra nhanh (sau khi xong toàn bộ)

```bash
curl https://mcp-server-production-xxxx.up.railway.app/health
curl https://webapp-production-yyyy.up.railway.app/health
# cả 2 đều phải trả "ok"
```

---

## Lưu ý quan trọng

- **2 project Railway độc lập hoàn toàn** (project cũ `mcp-rag` và project
  mới `rag-acme`) — dữ liệu, Postgres, domain đều tách biệt. Xoá 1 bên
  không ảnh hưởng bên kia.
- Nếu muốn **xoá dữ liệu test cũ và bắt đầu sạch**, đơn giản nhất là xoá
  toàn bộ project Railway cũ (Settings project → Danger Zone → Delete
  Project) sau khi đã chắc chắn project mới hoạt động ổn.
- Phân quyền hiện tại (nhắc lại): chỉ áp dụng ở **upload/xoá** qua web
  app. MCP server (`search_docs`) chưa lọc theo phòng ban người hỏi — xem
  lại phần "Giai đoạn 2" đã trao đổi nếu cần khép kín việc này.
