FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# 事業名は Cloud Run の環境変数 BUSINESS_NAME で切り替える
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 3600 core.entrypoint:app
