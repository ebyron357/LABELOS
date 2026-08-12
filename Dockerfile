# LABELOS API — production container image
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LABELOS_STORAGE_PATH=/data/storage \
    LABELOS_API_HOST=0.0.0.0 \
    LABELOS_API_PORT=8080

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY labelos ./labelos
COPY illustrator_bridge ./illustrator_bridge
COPY examples ./examples
COPY fixtures ./fixtures

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 labelos \
    && mkdir -p /data/storage \
    && chown -R labelos:labelos /data /app

USER labelos
VOLUME ["/data/storage"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${LABELOS_API_PORT}/health" || exit 1

# LABELOS_API_TOKEN must be provided at runtime. Never bake secrets into the image.
CMD ["labelos-api"]
