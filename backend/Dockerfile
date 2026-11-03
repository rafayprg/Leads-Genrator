# Backend API + background workers + Chromium (for website audits and PDFs).
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && python -m playwright install --with-deps chromium
# ssh: the Harvey bridge sends leads to Harvey on the host (app/harvey/bridge.py)
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client && rm -rf /var/lib/apt/lists/*
COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
RUN useradd --create-home --uid 10001 audit && mkdir -p /app/data && chown -R audit /app/data
USER audit
EXPOSE 8800
# migrations first, then the API (workers start inside it)
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8800 --proxy-headers"]
