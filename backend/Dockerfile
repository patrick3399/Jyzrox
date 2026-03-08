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

# Create gallery-dl config directory under /app (accessible by any user)
RUN mkdir -p /app/config && \
    echo '{}' > /app/config/gallery-dl.json && \
    chmod 777 /app/config /app/config/gallery-dl.json

USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
