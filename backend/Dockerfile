# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

# Install wheels for packages with C extensions (pillow, lxml, onnxruntime, etc.)
RUN pip install --no-cache-dir --upgrade pip

WORKDIR /install

COPY requirements.lock .
RUN pip install --no-cache-dir --prefix=/install/pkgs -r requirements.lock && \
    pip install --no-cache-dir --prefix=/install/pkgs gallery-dl && \
    pip install --no-cache-dir --no-deps --prefix=/install/pkgs thumbhash-python==1.0.1

# Download swagger-ui-dist static assets for self-hosted docs
RUN python -c "\
import urllib.request; \
urllib.request.urlretrieve('https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js', '/install/swagger-ui-bundle.js'); \
urllib.request.urlretrieve('https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css', '/install/swagger-ui.css')"

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

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

# Copy swagger-ui static assets
RUN mkdir -p /app/static/swagger-ui
COPY --from=builder /install/swagger-ui-bundle.js /app/static/swagger-ui/
COPY --from=builder /install/swagger-ui.css /app/static/swagger-ui/

RUN chown -R appuser:appgroup /app

# Create gallery-dl config directory under /app (owner: appuser, no world access)
RUN mkdir -p /app/config && \
    echo '{}' > /app/config/gallery-dl.json && \
    chown -R appuser:appgroup /app/config && \
    chmod 750 /app/config && \
    chmod 640 /app/config/gallery-dl.json

# Entrypoint runs as root to fix bind-mount ownership, then drops to appuser via gosu
COPY entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

# No USER directive — entrypoint.sh handles privilege drop via gosu
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
