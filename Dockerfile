# FORCE CAPITAL API (Phase 3 / P3-3) — Cloud Run 用
# ビルド: gcloud run deploy が自動ビルド(Buildpacks不使用・本Dockerfile優先)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 依存だけ先に入れてレイヤキャッシュを効かせる
COPY requirements.txt requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt

# APIが参照する層のみコピー(web/ や証券CSV等は .dockerignore で除外)
COPY api/ ./api/
COPY tabs/ ./tabs/
COPY calc.py config.py data.py jquants.py market.py ./

# Cloud Run は $PORT を注入する(既定8080)。--workers 1 = scale-to-zero前提の単一ユーザー用途
ENV PORT=8080
CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers 1
