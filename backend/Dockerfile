# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

# Install wheels for packages with C extensions (pillow, lxml, onnxruntime, etc.)
RUN pip install --no-cache-dir --upgrade pip

WORKDIR /install

COPY requirements.lock .
# GDL_VERSION pins the gallery-dl baked into the image (empty = latest at build
# time). Passing a new value also busts this layer's cache; without it a cached
# build keeps the old gallery-dl.
ARG GDL_VERSION=
RUN pip install --no-cache-dir --prefix=/install/pkgs -r requirements.lock && \
    pip download --no-cache-dir --dest /install/gdl-wheels "gallery-dl${GDL_VERSION:+==$GDL_VERSION}" "psycopg[binary]" && \
    pip install --no-cache-dir --prefix=/install/pkgs --no-index --find-links /install/gdl-wheels gallery-dl "psycopg[binary]"

# Download swagger-ui-dist static assets for self-hosted docs
RUN python -c "\
import urllib.request; \
urllib.request.urlretrieve('https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js', '/install/swagger-ui-bundle.js'); \
urllib.request.urlretrieve('https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css', '/install/swagger-ui.css')"

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

# gosu: privilege-drop in entrypoint; wget: healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        gosu \
        wget \
        ffmpeg \
    && install -d /usr/share/postgresql-common/pgdg \
    && wget -qO /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 git openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Create service account matching ZFS dataset owner (UID/GID 1042)
RUN groupadd -g 1042 appgroup && \
    useradd -u 1042 -g appgroup -m -s /bin/sh appuser

# Copy installed Python packages from builder
COPY --from=builder /install/pkgs /usr/local
# Wheels of the same gallery-dl, so the worker can rebuild the venv offline.
COPY --from=builder /install/gdl-wheels /opt/gdl-wheels

WORKDIR /app

COPY . .

# Bake db/init.sql into the image (repo-root db/ is outside this build context,
# supplied as the named build context `dbinit`). Lets migrate bootstrap a fresh
# DB from a pulled/pre-built image without a source-tree bind mount.
COPY --from=dbinit init.sql /app/db/init.sql

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
