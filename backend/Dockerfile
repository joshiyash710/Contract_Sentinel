# ContractSentinel backend — production image (see docs/DEPLOYMENT.md).
# Python 3.11 (pyproject pins >=3.11,<3.12) + uv for reproducible, locked installs.
#
# Runtime notes:
#  - Generation runs on Groq when LLM_PROVIDER=groq (no local LLM needed in this image).
#  - Embeddings (bge-m3) stay on Ollama, which runs on the VM HOST (not in this container).
#    From inside the container, 127.0.0.1 is NOT the host — reach host Ollama with either
#    `docker run --network host` (Linux, simplest) OR
#    `--add-host=host.docker.internal:host-gateway` + `OLLAMA_HOST=http://host.docker.internal:11434`.
#  - tesseract-ocr is the only OS package needed (pytesseract OCR fallback in the ingest node).
#  - Migrations run at container start (entrypoint) before uvicorn.

FROM python:3.11-slim-bookworm

# System deps: tesseract for OCR; ca-certificates for TLS to Groq/Google. Slim, no recommends.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv (fast, lockfile-faithful installer). Copied from the official distroless uv image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 1) Install deps first (cached until the lockfile changes). --no-dev = prod deps only.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) App source (changes most often → last layer).
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
# Feature 053: ship the prebuilt FAISS KB index so CRAG local retrieval works in prod (else all-web
# fallback). data/kb/ is git-tracked; rebuild it via HF (050 AC-10) before the image build for prod.
COPY data/kb ./data/kb
COPY docker-entrypoint.sh ./
RUN uv sync --frozen --no-dev \
    && chmod +x docker-entrypoint.sh

# Persistent data (SQLite DBs + encrypted uploads) lives here — mount a host volume at /app/data.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000

# Entrypoint runs `alembic upgrade head` then execs uvicorn. Bind 0.0.0.0 inside the container;
# publish it to 127.0.0.1 on the host so only the reverse proxy (Caddy) reaches it.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
