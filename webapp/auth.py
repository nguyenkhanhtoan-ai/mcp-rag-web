"""
Xác thực + phân quyền cho web app.

Session đơn giản bằng cookie ký (itsdangerous, qua Starlette SessionMiddleware)
- lưu user_id trong session, không cần thêm bảng session/JWT.
"""
from typing import Optional

from fastapi import Request, HTTPException
from starlette.status import HTTP_303_SEE_OTHER
from fastapi.responses import RedirectResponse

import db


def login_user(request: Request, user: dict):
    request.session["user_id"] = user["id"]


def logout_user(request: Request):
    request.session.clear()


def get_current_user(request: Request) -> Optional[dict]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get_user_by_id(user_id)
    if user is None or not user["is_active"]:
        return None
    return user


def require_login(request: Request) -> dict:
    """Dùng làm FastAPI dependency. Raise redirect về /login nếu chưa đăng nhập."""
    user = get_current_user(request)
    if user is None:
        raise _RedirectException("/login")
    return user


def require_role(request: Request, allowed_roles: tuple[str, ...]) -> dict:
    user = require_login(request)
    if user["role"] not in allowed_roles:
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập trang này.")
    return user


class _RedirectException(Exception):
    """Exception nội bộ để dependency có thể trigger redirect (xử lý ở exception handler)."""
    def __init__(self, location: str):
        self.location = location


def can_upload_to_department(user: dict, department_id: Optional[int]) -> bool:
    if user["role"] == "admin":
        return True
    if user["role"] == "uploader":
        return user["department_id"] == department_id
    return False


def can_delete_document(user: dict, doc_department_id: Optional[int]) -> bool:
    if user["role"] == "admin":
        return True
    if user["role"] == "uploader":
        return user["department_id"] == doc_department_id
    return False


def visible_department_id(user: dict) -> Optional[int]:
    """Trả về department_id để lọc danh sách tài liệu hiển thị.
    None nghĩa là xem được tất cả (chỉ admin)."""
    if user["role"] == "admin":
        return None
    return user["department_id"]
