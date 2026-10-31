FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml README.md LICENSE ./
COPY groceroute ./groceroute
COPY scripts ./scripts
RUN pip install --no-cache-dir . \
    && playwright install --with-deps chromium
