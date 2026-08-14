"""
Tiện ích đọc PDF (text-based) và chia nhỏ (chunk) văn bản.

Ghi chú: chunk theo xấp xỉ số ký tự (~4 ký tự/token, quy ước phổ biến cho
tiếng Anh; với tiếng Việt tỷ lệ có thể thấp hơn nhưng vẫn đủ dùng cho mục
đích chia chunk). Tránh phụ thuộc tiktoken để không cần tải file BPE từ
mạng ngoài lúc chạy lần đầu.
"""
import io
from pathlib import Path
from typing import Iterator, NamedTuple, Union

from pypdf import PdfReader

from config import CHUNK_SIZE, CHUNK_OVERLAP

_CHARS_PER_TOKEN = 4


class Chunk(NamedTuple):
    text: str
    source: str      # tên file
    page: int         # số trang (1-indexed)
    chunk_index: int  # thứ tự chunk trong trang


def extract_pages(pdf_source: Union[Path, io.BytesIO]) -> Iterator[tuple[int, str]]:
    """Yield (page_number, text) cho từng trang có chữ trong PDF.

    pdf_source có thể là đường dẫn file (Path) hoặc stream bytes (BytesIO) -
    dùng BytesIO khi đọc PDF upload trực tiếp từ web, không cần ghi ra đĩa.
    """
    source = str(pdf_source) if isinstance(pdf_source, Path) else pdf_source
    reader = PdfReader(source)
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = text.strip()
        if text:
            yield i, text


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Chia text thành các chunk theo số ký tự (ước lượng từ số token), có overlap."""
    char_size = chunk_size * _CHARS_PER_TOKEN
    char_overlap = overlap * _CHARS_PER_TOKEN

    if len(text) <= char_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + char_size, len(text))
        # Cố gắng cắt tại khoảng trắng gần cuối để không chặt giữa từ
        if end < len(text):
            last_space = text.rfind(" ", start, end)
            if last_space > start:
                end = last_space
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - char_overlap
    return [c for c in chunks if c]


def process_pdf(pdf_path: Path) -> list[Chunk]:
    """Đọc 1 file PDF từ đường dẫn, trả về danh sách Chunk đã chia nhỏ theo trang."""
    return process_pdf_source(pdf_path, source_name=pdf_path.name)


def process_pdf_bytes(data: bytes, source_name: str) -> list[Chunk]:
    """Đọc 1 file PDF từ bytes (vd: file upload trên web), không cần ghi ra đĩa."""
    return process_pdf_source(io.BytesIO(data), source_name=source_name)


def process_pdf_source(pdf_source: Union[Path, io.BytesIO], source_name: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page_num, page_text in extract_pages(pdf_source):
        for idx, piece in enumerate(chunk_text(page_text)):
            chunks.append(
                Chunk(
                    text=piece,
                    source=source_name,
                    page=page_num,
                    chunk_index=idx,
                )
            )
    return chunks
