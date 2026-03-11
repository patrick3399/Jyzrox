# ── Build stage ────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ──────────────────────────────────────────────────────
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends wget \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1042 appuser \
    && useradd -u 1042 -g appuser -m appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY app.py .

ENV HF_HOME=/app/models \
    PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8100

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
