"""
Script tạo tài khoản admin đầu tiên (chạy 1 lần lúc setup).

Cách dùng:
    python init_admin.py --email admin@company.com --password "matkhaumanh" --name "Admin"

Hoặc lấy từ biến môi trường ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_NAME
(tiện cho việc chạy tự động lúc deploy, ví dụ qua `railway run python init_admin.py`).
"""
import argparse
import os
import sys

import db


def main():
    parser = argparse.ArgumentParser(description="Tạo tài khoản admin đầu tiên")
    parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD"))
    parser.add_argument("--name", default=os.environ.get("ADMIN_NAME", "Administrator"))
    args = parser.parse_args()

    if not args.email or not args.password:
        print("Cần cung cấp --email và --password (hoặc ADMIN_EMAIL/ADMIN_PASSWORD).", file=sys.stderr)
        sys.exit(1)

    if len(args.password) < 8:
        print("Mật khẩu nên dài tối thiểu 8 ký tự.", file=sys.stderr)
        sys.exit(1)

    db.init_admin_db()

    existing = db.get_user_by_email(args.email)
    if existing:
        print(f"User {args.email} đã tồn tại (role={existing['role']}). Không tạo mới.")
        sys.exit(0)

    user_id = db.create_user(args.email, args.password, args.name, "admin", None)
    print(f"Đã tạo admin: {args.email} (id={user_id})")


if __name__ == "__main__":
    main()
