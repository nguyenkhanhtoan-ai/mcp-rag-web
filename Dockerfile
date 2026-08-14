FROM python:3.12-slim

WORKDIR /app

# Cài dependencies trước để tận dụng Docker layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

# Ingest KHÔNG chạy ở đây - Postgres là 1 service riêng, build không kết nối
# tới được. Ingest bằng `railway run python ingest.py` sau khi deploy, hoặc
# kết nối trực tiếp bằng DATABASE_URL public (xem DEPLOY.md).
CMD ["python", "server.py"]
