# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 coven

COPY pyproject.toml README.md ./
COPY src ./src
COPY web ./web
RUN pip install ".[aws]"

USER coven
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"

CMD ["uvicorn", "coven.cloud.app:app", "--host", "0.0.0.0", "--port", "8080"]
