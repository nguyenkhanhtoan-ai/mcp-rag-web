# Build context PHẢI là thư mục gốc project (mcp-rag-pdf/), không phải webapp/,
# vì cần copy các module dùng chung (config.py, pdf_utils.py, vector_store.py).
# Trên Railway: Settings -> Build -> Dockerfile Path = webapp/Dockerfile,
# Root Directory để trống/mặc định (= gốc repo).

FROM python:3.12-slim

WORKDIR /app

COPY webapp/requirements.txt ./webapp-requirements.txt
RUN pip install --no-cache-dir -r webapp-requirements.txt

# Module dùng chung với MCP server (ingest, pdf, vector store)
COPY config.py pdf_utils.py vector_store.py ./

COPY webapp/ ./webapp/

WORKDIR /app/webapp

ENV PORT=8001

EXPOSE 8001

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
