# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

# Install wheels for packages with C extensions (pillow, lxml, onnxruntime, etc.)
RUN pip install --no-cache-dir --upgrade pip

WORKDIR /install

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install/pkgs -r requirements.txt && \
    pip install --no-cache-dir --prefix=/install/pkgs gallery-dl

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# gosu: privilege-drop in entrypoint; wget: healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        gosu \
        wget \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create service account matching ZFS dataset owner (UID/GID 1042)
RUN groupadd -g 1042 appgroup && \
    useradd -u 1042 -g appgroup -m -s /bin/sh appuser

# Copy installed Python packages from builder
COPY --from=builder /install/pkgs /usr/local

WORKDIR /app

COPY . .
RUN chown -R appuser:appgroup /app

# Create gallery-dl config directory under /app (owner: appuser, no world access)
RUN mkdir -p /app/config && \
    echo '{}' > /app/config/gallery-dl.json && \
    chown -R appuser:appgroup /app/config && \
    chmod 750 /app/config && \
    chmod 640 /app/config/gallery-dl.json

# Entrypoint runs as root to fix bind-mount ownership, then drops to appuser via gosu
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# No USER directive — entrypoint.sh handles privilege drop via gosu
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
