# pptx-renderer — LibreOffice headless wrapped in a tiny FastAPI service.
#
# Image size sits around 1.0 GB because LibreOffice carries every locale
# pack, font fallback set, and Java runtime. We accept the bulk because
# the alternative (stripping locale+font packs) breaks rendering on the
# very corporate templates this exists to support (Arabic, Chinese,
# proprietary corporate typefaces).
#
# Build context must be the **repository root** so `uv` can read the
# workspace `pyproject.toml` + `uv.lock` and install with `--frozen`.
#
# Two notable choices:
#  * debian-slim base, not alpine. LibreOffice on alpine is half-broken
#    and missing fonts; debian's libreoffice apt package "just works".
#  * libreoffice-impress only, not the full suite — we don't need
#    Writer or Calc for .pptx → .png.

FROM python:3.11.9-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# System deps. ``--no-install-recommends`` keeps Office's heavy
# extras (translation help, training docs) out. ``fonts-liberation``
# + ``fonts-dejavu`` give us safe sans/serif fallbacks for any
# template that references a font not embedded in the file.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-impress \
        libreoffice-core \
        poppler-utils \
        fonts-liberation \
        fonts-dejavu \
        ca-certificates \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# poppler-utils gives us ``pdftoppm``, the canonical pdf→png splitter.
# We can't use libreoffice's ``--convert-to png`` directly because it
# only renders the first slide of a multi-slide deck. Two-stage
# conversion (.pptx → .pdf via libreoffice, .pdf → page-N.png via
# pdftoppm) is the standard pattern for full-deck rendering.

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY tempslide ./tempslide
COPY server ./server

RUN uv sync --package pptx-renderer --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

WORKDIR /app/server/pptx-renderer

# 8002 matches docker-compose.yml + the backend client default URL.
EXPOSE 8002

# ``--workers 1`` because LibreOffice is process-heavy: each worker
# spawns its own libreoffice subprocess for every render. Two workers
# in parallel doubles RAM. Scale horizontally (more containers) when
# we need throughput, not by upping workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "1"]
