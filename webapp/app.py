"""
Web app quản lý upload PDF, phân quyền theo user/phòng ban.

Chạy local:
    export DATABASE_URL=postgresql://...
    export OPENAI_API_KEY=sk-...
    export SESSION_SECRET=doi-chuoi-nay
    uvicorn app:app --reload --port 8001

Lần đầu chạy, tạo tài khoản admin bằng:
    python init_admin.py
"""
import hashlib
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request, Form, UploadFile, File, BackgroundTasks
from fastapi.responses import RedirectResponse, HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_303_SEE_OTHER

import db
import ingest_core
import auth
from auth import _RedirectException

SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
if not SESSION_SECRET:
    raise RuntimeError(
        "Chưa set SESSION_SECRET. Tạo 1 chuỗi ngẫu nhiên dài, ví dụ:\n"
        "  python -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "rồi set biến môi trường SESSION_SECRET."
    )

MAX_UPLOAD_MB = 30

app = FastAPI(title="RAG PDF Manager")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, https_only=False)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.on_event("startup")
def startup():
    db.init_admin_db()
    import vector_store
    vector_store.init_db()


@app.exception_handler(_RedirectException)
def handle_redirect(request: Request, exc: _RedirectException):
    return RedirectResponse(exc.location, status_code=HTTP_303_SEE_OTHER)


def _flash_redirect(location: str, success: str = None, error: str = None):
    sep = "&" if "?" in location else "?"
    if success:
        location = f"{location}{sep}success={success}"
    elif error:
        location = f"{location}{sep}error={error}"
    return RedirectResponse(location, status_code=HTTP_303_SEE_OTHER)


# ---------- Auth ----------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if auth.get_current_user(request):
        return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "login.html", {"user": None})


@app.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    user = db.get_user_by_email(email)
    if user is None or not user["is_active"] or not db.verify_password(password, user["password_hash"]):
        return _flash_redirect("/login", error="Email hoặc mật khẩu không đúng.")
    auth.login_user(request, user)
    return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)


@app.get("/logout")
def logout(request: Request):
    auth.logout_user(request)
    return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)


# ---------- Dashboard ----------

DOCS_PER_PAGE = 5


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, page: int = 1):
    user = auth.require_login(request)
    page = max(1, page)

    if user["role"] != "admin" and user["department_id"] is None:
        # User không có phòng ban -> KHÔNG được xem tài liệu của bất kỳ ai
        # (tránh nhầm lẫn với admin, nơi department_id=None nghĩa là "xem tất cả").
        documents, total_docs, total_pages, dept_stats = [], 0, 1, None
    else:
        dept_filter = auth.visible_department_id(user)
        total_docs = db.count_documents(department_id=dept_filter)
        total_pages = max(1, (total_docs + DOCS_PER_PAGE - 1) // DOCS_PER_PAGE)
        page = min(page, total_pages)
        offset = (page - 1) * DOCS_PER_PAGE
        documents = db.list_documents(department_id=dept_filter, limit=DOCS_PER_PAGE, offset=offset)
        # Thống kê: admin xem theo từng phòng ban, người khác chỉ xem tổng của phòng mình
        dept_stats = db.count_documents_by_department() if user["role"] == "admin" else None

    departments = db.list_departments()

    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user, "documents": documents, "departments": departments,
        "total_docs": total_docs, "dept_stats": dept_stats,
        "current_page": page, "total_pages": total_pages,
    })


@app.post("/upload")
async def upload(request: Request, background_tasks: BackgroundTasks,
                  file: UploadFile = File(...), department_id: str = Form(...)):
    user = auth.require_role(request, ("admin", "uploader"))
    dept_id = int(department_id)

    if not auth.can_upload_to_department(user, dept_id):
        return _flash_redirect("/", error="Bạn không có quyền upload vào phòng ban này.")

    if not file.filename.lower().endswith(".pdf"):
        return _flash_redirect("/", error="Chỉ chấp nhận file .pdf")

    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        return _flash_redirect("/", error=f"File vượt quá {MAX_UPLOAD_MB}MB.")

    content_hash = hashlib.sha256(data).hexdigest()[:16]
    doc_id = db.create_document(file.filename, content_hash, data, dept_id, user["id"])
    db.add_audit_log(user["id"], "upload", doc_id, f"Uploaded {file.filename}")

    background_tasks.add_task(ingest_core.ingest_document, doc_id)

    return _flash_redirect("/", success=f"Đã upload '{file.filename}', đang xử lý ingest...")


@app.post("/documents/{document_id}/delete")
def delete_document(request: Request, document_id: int):
    user = auth.require_login(request)
    doc = db.get_document(document_id)
    if doc is None:
        return _flash_redirect("/", error="Không tìm thấy tài liệu.")

    if not auth.can_delete_document(user, doc["department_id"]):
        return _flash_redirect("/", error="Bạn không có quyền xoá tài liệu này.")

    import vector_store
    vector_store.delete_by_document_id(document_id)
    db.delete_document(document_id)
    db.add_audit_log(user["id"], "delete", document_id, f"Deleted {doc['filename']}")

    return _flash_redirect("/", success=f"Đã xoá '{doc['filename']}'.")


# ---------- Admin: users ----------

@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request):
    user = auth.require_role(request, ("admin",))
    return templates.TemplateResponse(request, "admin_users.html", {
        "user": user,
        "users": db.list_users(), "departments": db.list_departments(),
    })


@app.post("/admin/users/create")
def admin_create_user(request: Request, name: str = Form(...), email: str = Form(...),
                       password: str = Form(...), role: str = Form(...),
                       department_id: str = Form("")):
    auth.require_role(request, ("admin",))
    dept_id = int(department_id) if department_id else None
    try:
        db.create_user(email, password, name, role, dept_id)
    except Exception as e:  # noqa: BLE001
        return _flash_redirect("/admin/users", error=f"Lỗi tạo user: {e}")
    return _flash_redirect("/admin/users", success=f"Đã tạo user {email}.")


@app.post("/admin/users/{user_id}/toggle-active")
def admin_toggle_active(request: Request, user_id: int):
    current = auth.require_role(request, ("admin",))
    target = db.get_user_by_id(user_id)
    if target is None:
        return _flash_redirect("/admin/users", error="Không tìm thấy user.")
    if target["is_active"] and target["role"] == "admin" and db.count_admins(exclude_user_id=user_id) == 0:
        return _flash_redirect("/admin/users", error="Không thể khoá admin cuối cùng.")
    db.update_user(user_id, is_active=not target["is_active"])
    return _flash_redirect("/admin/users", success="Đã cập nhật trạng thái user.")


@app.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
def admin_edit_user_page(request: Request, user_id: int):
    current = auth.require_role(request, ("admin",))
    target = db.get_user_by_id(user_id)
    if target is None:
        return _flash_redirect("/admin/users", error="Không tìm thấy user.")
    return templates.TemplateResponse(request, "admin_user_edit.html", {
        "user": current, "target": target, "departments": db.list_departments(),
    })


@app.post("/admin/users/{user_id}/edit")
def admin_edit_user_save(request: Request, user_id: int, name: str = Form(...),
                          email: str = Form(...), role: str = Form(...),
                          department_id: str = Form(""), password: str = Form("")):
    current = auth.require_role(request, ("admin",))
    target = db.get_user_by_id(user_id)
    if target is None:
        return _flash_redirect("/admin/users", error="Không tìm thấy user.")

    if user_id == current["id"] and role != "admin" and db.count_admins(exclude_user_id=user_id) == 0:
        return _flash_redirect(f"/admin/users/{user_id}/edit", error="Không thể tự hạ quyền admin cuối cùng.")

    if password and len(password) < 8:
        return _flash_redirect(f"/admin/users/{user_id}/edit", error="Mật khẩu mới phải tối thiểu 8 ký tự.")

    dept_id = int(department_id) if department_id else None
    try:
        db.update_user(
            user_id, name=name, email=email, role=role, department_id=dept_id,
            password=password if password else None,
        )
    except Exception as e:  # noqa: BLE001
        return _flash_redirect(f"/admin/users/{user_id}/edit", error=f"Lỗi cập nhật: {e}")

    return _flash_redirect("/admin/users", success=f"Đã cập nhật user {email}.")


@app.post("/admin/users/{user_id}/delete")
def admin_delete_user(request: Request, user_id: int):
    current = auth.require_role(request, ("admin",))
    target = db.get_user_by_id(user_id)
    if target is None:
        return _flash_redirect("/admin/users", error="Không tìm thấy user.")

    if user_id == current["id"]:
        return _flash_redirect("/admin/users", error="Không thể tự xoá chính mình. Nhờ admin khác xoá giúp.")

    if target["role"] == "admin" and target["is_active"] and db.count_admins(exclude_user_id=user_id) == 0:
        return _flash_redirect("/admin/users", error="Không thể xoá admin cuối cùng.")

    db.delete_user(user_id)
    return _flash_redirect("/admin/users", success=f"Đã xoá user {target['email']}.")


# ---------- Admin: departments ----------

@app.get("/admin/departments", response_class=HTMLResponse)
def admin_departments(request: Request):
    user = auth.require_role(request, ("admin",))
    departments = db.list_departments()
    for d in departments:
        d["user_count"] = db.count_users_in_department(d["id"])
        d["doc_count"] = db.count_documents(department_id=d["id"])
    return templates.TemplateResponse(request, "admin_departments.html", {
        "user": user, "departments": departments,
    })


@app.post("/admin/departments/create")
def admin_create_department(request: Request, name: str = Form(...)):
    auth.require_role(request, ("admin",))
    db.create_department(name.strip())
    return _flash_redirect("/admin/departments", success=f"Đã thêm phòng ban '{name}'.")


@app.get("/admin/departments/{department_id}/edit", response_class=HTMLResponse)
def admin_edit_department_page(request: Request, department_id: int):
    user = auth.require_role(request, ("admin",))
    dept = db.get_department(department_id)
    if dept is None:
        return _flash_redirect("/admin/departments", error="Không tìm thấy phòng ban.")
    return templates.TemplateResponse(request, "admin_department_edit.html", {
        "user": user, "dept": dept,
    })


@app.post("/admin/departments/{department_id}/edit")
def admin_edit_department_save(request: Request, department_id: int, name: str = Form(...)):
    auth.require_role(request, ("admin",))
    if db.get_department(department_id) is None:
        return _flash_redirect("/admin/departments", error="Không tìm thấy phòng ban.")
    name = name.strip()
    if not name:
        return _flash_redirect(f"/admin/departments/{department_id}/edit", error="Tên phòng ban không được để trống.")
    try:
        db.update_department(department_id, name)
    except Exception as e:  # noqa: BLE001
        return _flash_redirect(f"/admin/departments/{department_id}/edit", error=f"Lỗi cập nhật: {e}")
    return _flash_redirect("/admin/departments", success=f"Đã cập nhật phòng ban thành '{name}'.")


@app.post("/admin/departments/{department_id}/delete")
def admin_delete_department(request: Request, department_id: int):
    auth.require_role(request, ("admin",))
    dept = db.get_department(department_id)
    if dept is None:
        return _flash_redirect("/admin/departments", error="Không tìm thấy phòng ban.")

    user_count = db.count_users_in_department(department_id)
    doc_count = db.count_documents(department_id=department_id)
    if user_count > 0 or doc_count > 0:
        return _flash_redirect(
            "/admin/departments",
            error=(
                f"Không thể xoá '{dept['name']}': còn {user_count} user và {doc_count} tài liệu "
                "đang gắn với phòng ban này. Hãy chuyển họ sang phòng ban khác trước."
            ),
        )

    db.delete_department(department_id)
    return _flash_redirect("/admin/departments", success=f"Đã xoá phòng ban '{dept['name']}'.")


# ---------- Admin: audit log ----------

@app.get("/admin/audit-log", response_class=HTMLResponse)
def admin_audit_log(request: Request):
    user = auth.require_role(request, ("admin",))
    return templates.TemplateResponse(request, "admin_audit_log.html", {
        "user": user, "logs": db.list_audit_log(),
    })


@app.get("/health")
def health():
    return PlainTextResponse("ok")
