"""
MCP server expose tool RAG search trên các PDF đã ingest.

Chỉ hỗ trợ HTTP transport (streamable-http) - dùng cho deploy cloud và kết
nối qua Claude Connectors (Settings -> Connectors -> Add custom connector).

Chạy:
    python server.py

Đăng ký remote connector: xem DEPLOY.md
"""
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from config import DEFAULT_TOP_K
import vector_store

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

mcp = FastMCP("rag-pdf", host=HOST, port=PORT)


@mcp.tool()
def search_docs(query: str, top_k: int = DEFAULT_TOP_K, tags: Optional[list[str]] = None) -> str:
    """
    Tìm kiếm ngữ nghĩa (semantic search) trong kho tài liệu PDF đã được index.

    Dùng tool này khi cần tra cứu thông tin, trích dẫn, hoặc trả lời câu hỏi
    dựa trên nội dung các file PDF mà người dùng đã nạp vào hệ thống.

    Args:
        query: câu hỏi hoặc từ khóa cần tìm.
        top_k: số đoạn kết quả liên quan nhất cần trả về (mặc định 5).
        tags: (tuỳ chọn) danh sách chủ đề/tag để lọc TRƯỚC khi tìm kiếm
            ngữ nghĩa - chỉ tìm trong các tài liệu có ít nhất 1 tag khớp.
            Giúp thu hẹp phạm vi, tăng độ chính xác khi kho tài liệu lớn
            hoặc câu hỏi rõ ràng thuộc 1 chủ đề cụ thể (ví dụ tags=["HR"]
            khi hỏi về quy trình nhân sự). Dùng list_tags trước để biết
            các chủ đề đang có. Để trống nếu muốn tìm trên toàn bộ kho.

    Returns:
        Danh sách các đoạn văn bản liên quan nhất, kèm nguồn (tên file + trang + tag).
    """
    if vector_store.count() == 0:
        return (
            "Kho tài liệu hiện đang trống. Hãy chạy `python ingest.py` để nạp "
            "PDF từ thư mục documents/ trước khi tìm kiếm."
        )

    query_embedding = vector_store.embed_texts([query])[0]
    results = vector_store.query(query_embedding, top_k=max(1, min(top_k, 20)), tags=tags)

    if not results:
        if tags:
            return f"Không tìm thấy đoạn nào khớp với tag {tags} cho truy vấn này. Thử bỏ bớt tag hoặc dùng list_tags để xem các chủ đề hiện có."
        return "Không tìm thấy đoạn nào liên quan đến truy vấn này."

    parts = []
    for i, r in enumerate(results, start=1):
        similarity = round(r["similarity"], 3)
        tag_str = f", tags: {r['tags']}" if r.get("tags") else ""
        parts.append(
            f"[{i}] Nguồn: {r['source']} (trang {r['page']}{tag_str}) "
            f"- độ liên quan: {similarity}\n{r['document']}"
        )

    return "\n\n---\n\n".join(parts)


@mcp.tool()
def list_tags() -> str:
    """
    Liệt kê tất cả chủ đề/tag hiện đang được gắn cho tài liệu trong kho.

    Dùng tool này TRƯỚC khi gọi search_docs với tham số tags, để biết chính
    xác các chủ đề đang tồn tại (tránh lọc theo tag không có thật -> ra 0
    kết quả).
    """
    tags = vector_store.list_all_tags()
    if not tags:
        return "Chưa có tag nào được gắn cho tài liệu trong kho."
    return "Các chủ đề/tag hiện có: " + ", ".join(tags)


@mcp.tool()
def get_document_content(filename: str) -> str:
    """
    Lấy TOÀN BỘ nội dung của 1 file PDF cụ thể (không chỉ các đoạn liên
    quan nhất như search_docs), sắp xếp đúng thứ tự trang.

    Dùng tool này khi cần đọc/tóm tắt trọn vẹn 1 tài liệu - ví dụ khi tổng
    hợp nhiều tài liệu để phân tích, đề xuất mô hình tổ chức, hoặc bất kỳ
    tác vụ nào cần hiểu đầy đủ nội dung thay vì chỉ các đoạn liên quan tới
    1 câu hỏi cụ thể. Dùng list_indexed_documents trước để biết tên file
    chính xác.

    Args:
        filename: tên file chính xác (lấy từ list_indexed_documents).

    Returns:
        Toàn bộ nội dung file, các đoạn được nối theo đúng thứ tự trang.
    """
    chunks = vector_store.get_full_document(filename)
    if not chunks:
        return (
            f"Không tìm thấy file '{filename}' trong kho tài liệu. "
            "Dùng list_indexed_documents để xem tên file chính xác."
        )

    full_text = "\n".join(c["document"] for c in chunks)

    MAX_CHARS = 60000  # ~15k token, đủ cho hầu hết tài liệu, tránh 1 file cực lớn chiếm hết context
    if len(full_text) > MAX_CHARS:
        full_text = (
            full_text[:MAX_CHARS]
            + f"\n\n[... nội dung bị cắt bớt, file dài hơn {MAX_CHARS} ký tự. "
            "Cân nhắc dùng search_docs với câu hỏi cụ thể hơn cho phần còn lại ...]"
        )

    return f"=== {filename} ({len(chunks)} đoạn) ===\n\n{full_text}"


@mcp.tool()
def list_indexed_documents() -> str:
    """
    Liệt kê danh sách các file PDF hiện đã được index trong kho tài liệu,
    kèm số lượng chunk (đoạn văn bản) của mỗi file.

    Dùng tool này khi cần biết kho tài liệu hiện có gì trước khi tìm kiếm.
    """
    sources = vector_store.list_sources()
    if not sources:
        return "Kho tài liệu hiện đang trống. Hãy chạy `python ingest.py` trước."

    lines = [f"- {name}: {count} chunks" for name, count in sources.items()]
    total = sum(sources.values())
    return f"Tổng {len(sources)} file, {total} chunks:\n" + "\n".join(lines)


def _run_http():
    """Chạy server ở chế độ HTTP (streamable-http)."""
    import uvicorn
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    vector_store.init_db()  # đảm bảo extension/table/index đã tồn tại

    app = mcp.streamable_http_app()
    # Endpoint đơn giản để cloud platform (Railway/Fly.io) kiểm tra health
    app.router.routes.insert(0, Route("/health", lambda request: PlainTextResponse("ok")))

    print(f"[server] Listening on http://{HOST}:{PORT}/mcp")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    _run_http()
