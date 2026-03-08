FROM python:3.12-slim

# Create service account matching ZFS dataset owner (UID/GID 1042)
RUN groupadd -g 1042 appgroup && \
    useradd -u 1042 -g appgroup -m -s /bin/sh appuser

WORKDIR /app

# Install dependencies as root before switching user
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gallery-dl

COPY . .
RUN chown -R appuser:appgroup /app

# Create gallery-dl config directory under /app (owner: appuser, no world access)
RUN mkdir -p /app/config && \
    echo '{}' > /app/config/gallery-dl.json && \
    chown -R appuser:appgroup /app/config && \
    chmod 750 /app/config && \
    chmod 640 /app/config/gallery-dl.json

USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
