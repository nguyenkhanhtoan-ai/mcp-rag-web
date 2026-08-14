"""
Logic ingest dùng chung cho web app: nhận 1 document đã lưu trong bảng
documents (Postgres), chunk + embed + ghi vào pdf_chunks, cập nhật status.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pdf_utils  # noqa: E402
import vector_store  # noqa: E402
from config import EMBEDDING_BATCH_SIZE  # noqa: E402

import db  # noqa: E402


def ingest_document(document_id: int):
    """Chunk + embed + lưu vector cho 1 document đã có trong bảng documents.
    Cập nhật status 'ingesting' -> 'ingested'/'failed'. Ghi audit log.
    An toàn để gọi lại nhiều lần (xoá chunk cũ trước khi ingest lại)."""
    doc = db.get_document(document_id)
    if doc is None:
        return

    db.update_document_status(document_id, "ingesting")
    vector_store.delete_by_document_id(document_id)

    try:
        file_data = db.get_document_file(document_id)
        chunks = pdf_utils.process_pdf_bytes(file_data, source_name=doc["filename"])

        if not chunks:
            db.update_document_status(
                document_id, "failed",
                error_message="Không trích được text từ PDF (có thể là bản scan/ảnh).",
            )
            db.add_audit_log(doc["uploaded_by"], "ingest_failed", document_id,
                              "Không trích được text (PDF scan?)")
            return

        total = 0
        for i in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
            batch = chunks[i: i + EMBEDDING_BATCH_SIZE]
            embeddings = vector_store.embed_texts([c.text for c in batch])
            rows = [
                {
                    "id": f"doc{document_id}::p{c.page}::c{c.chunk_index}::{doc['content_hash']}",
                    "source": c.source,
                    "page": c.page,
                    "chunk_index": c.chunk_index,
                    "content_hash": doc["content_hash"],
                    "document": c.text,
                    "embedding": emb,
                    "document_id": document_id,
                }
                for c, emb in zip(batch, embeddings)
            ]
            vector_store.add_chunks(rows)
            total += len(batch)

        db.update_document_status(document_id, "ingested", chunk_count=total)
        db.add_audit_log(doc["uploaded_by"], "ingest_success", document_id, f"{total} chunks")

    except Exception as e:  # noqa: BLE001
        db.update_document_status(document_id, "failed", error_message=str(e)[:500])
        db.add_audit_log(doc["uploaded_by"], "ingest_failed", document_id, str(e)[:500])
        raise
