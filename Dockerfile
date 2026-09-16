FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic.ini main.py ./

RUN pip install --upgrade pip \
 && pip install ".[postgres]"

RUN useradd --create-home --uid 10001 kodostars \
 && mkdir -p /app/data \
 && chown -R kodostars:kodostars /app
USER kodostars

VOLUME ["/app/data"]

CMD ["python", "-m", "app"]
