# Temp Slide

Local development setup for the Edwin slide generator stack.

## Quick start

1. **Install tooling:** [uv](https://docs.astral.sh/uv/) and **Node.js** (CI uses **22**; LTS is fine locally). **Docker** for Postgres/Redis/Azurite (and optional `pptx-renderer`).
2. **From the repository root**, create the Python env and install JS deps:

   ```bash
   uv sync --group dev
   # Reproducible installs (matches CI): use npm ci when you are not changing package.json.
   npm ci --prefix client/app
   npm ci --prefix client/admin
   ```

   Use **`npm install --prefix …`** only when you intentionally change frontend dependencies (then commit the updated **`package-lock.json`**). CI always uses **`npm ci`**.

3. **Copy env templates** into the ignored `.env` files (see [Configuration](#configuration)).
4. **Start infra:** `docker compose up -d` (see [Backing services (Docker Compose)](#backing-services-docker-compose)).
5. **Run migrations** then **start** the db-service, backend, and frontends (see [Running application services](#running-application-services)).

---

## Local services (ports)

| Service        | URL / host                         |
| -------------- | ---------------------------------- |
| Postgres       | `localhost:5432`                   |
| Redis          | `localhost:6379`                   |
| DB service API | `http://localhost:8001`            |
| Backend API    | `http://localhost:8000`            |
| App (Vite)     | `http://localhost:5173`            |
| Admin (Vite)   | `http://localhost:5174`            |
| pptx-renderer  | `http://localhost:8002` (optional) |

---

## Python toolchain (`uv`)

### What this repo uses

- A **single uv workspace** at the repo root: **`pyproject.toml`** + **`uv.lock`**.
- All `server/**` packages are **workspace members**; internal distributions (`langfuse-client`, `llm-provider`, `app-logger`, `pptx-master`, `postgresql`) resolve via **`[tool.uv.sources]`**, not from PyPI.
- A minimal **`tempslide/`** package exists so the root project is buildable under Hatchling.

### Python version

- **Supported line:** **`requires-python = ">=3.11,<3.12"`** everywhere in the workspace.
- **`.python-version`** (e.g. `3.11.9`) is a **local hint** for uv/pyenv. **CI** and the **`pptx-renderer` Dockerfile** use **CPython 3.11** (`python:3.11.9-slim-bookworm` in Docker).

### Install commands

From the **repository root**:

```bash
# Runtime dependencies only (no pytest, Ruff, etc.)
uv sync

# Local dev: full workspace + dev tools (pytest, Ruff, …)
uv sync --group dev
```

The virtual environment is **`.venv/`** at the repo root.

Do **not** use **`uv pip install -e …`** as the main workflow; it bypasses the lockfile and will not match CI.

### Corporate TLS (Windows)

If **`uv lock`** or **`uv python install`** fails with certificate errors, try:

```powershell
$env:UV_NATIVE_TLS = "true"
```

---

## Backing services (Docker Compose)

Infra matches **`docker-compose.yml`** (Postgres, Redis, Azurite; optional **`pptx-renderer`**).

```bash
docker compose up -d
```

**`pptx-renderer`** is not started by default for every dev machine (large image). Build and run when you need layout PNG previews:

```bash
docker compose build pptx-renderer
docker compose up -d pptx-renderer
```

The image build uses **repo root** as context (see **`docker-compose.yml`**) so **`uv.lock`** is available to the Dockerfile.

---

## Configuration

Local **`.env`** files are gitignored. Create them from examples / team docs:

- `server/backend/.env` — see `server/backend/.env.example`
- `server/db-service/.env`
- `client/app/.env`
- `client/admin/.env`

The backend and DB service validate Azure AD tokens against Microsoft JWKS and use **`certifi`** as the default CA bundle. If your network uses TLS inspection, export **one** of **`SSL_CERT_FILE`**, **`REQUESTS_CA_BUNDLE`**, or **`AZURE_CACERT_PATH`** in the **process environment** (shell, IDE run configuration, or container) so OpenSSL sees a PEM bundle on disk. Do **not** commit org CA bundles into this repository unless there is an explicit, documented pinned-bundle policy.

### Repository hygiene

- **Do not commit secrets** — API keys, tokens, `.env` files, private keys, PEMs, or cloud service-account JSON belong in local files or your secret store, not in git.
- **Custom CA bundles** — keep them outside the repo and wire them in via env vars (see above). The repo does **not** ship a corporate CA file.
- **Backend lockfile** — after changing any Python dependency under **`server/**`**, run **`uv lock`** at the repo root and commit the updated **`uv.lock`**. CI runs **`uv lock --check`** so drift fails the build.
- **Frontend installs** — use **`npm install`** when you change **`package.json`** and need a new lockfile entry; use **`npm ci`** for clean, reproducible installs (including locally when mirroring CI).

---

## Running application services

Run each block in a **separate terminal**, from the **repository root**.

**DB service** (migrations once, then API):

```bash
PYTHONPATH=. uv run --directory server/db-service alembic upgrade head
PYTHONPATH=. uv run --directory server/db-service uvicorn app.main:app --reload --port 8001
```

**Backend API:**

```bash
PYTHONPATH=. uv run --directory server/backend uvicorn app.main:app --reload --port 8000
```

**Frontends:**

```bash
npm run dev --prefix client/app -- --host 127.0.0.1 --port 5173
npm run dev --prefix client/admin -- --host 127.0.0.1 --port 5174
```

**PowerShell** (same commands; set location once):

```powershell
Set-Location <path-to-Temp-Slide>
$env:PYTHONPATH = "."
uv run --directory server/db-service alembic upgrade head
# then in another window:
uv run --directory server/db-service uvicorn app.main:app --reload --port 8001
```

---

## Testing

Install dev tools first: **`uv sync --group dev`**.

### Makefile (recommended)

```bash
make help          # list targets
make install       # uv sync --group dev
make verify        # all Python + Vitest suites (same shape as local “full check”)
make test          # backend + db-service pytest only
make test-backend
make test-db-service
make test-app
make test-admin
make format-check  # ruff format --check
make lint          # ruff check
make type-check    # no-op until mypy/pyright is added
```

### Commands aligned with CI

CI runs **pptx-master** tests as well. Locally:

```bash
uv run --directory server/libs/pptx_master pytest tests -q
uv run --directory server/db-service pytest tests -q
uv run --directory server/backend pytest tests -q
```

Use **`PYTHONPATH=.`** when running from a service directory (as **`make test-backend`** does), or run from the repo root with **`uv run --directory …`** as above.

**Backend on GitHub Actions:** the workflow sets **`CI=true`**, so tests load **`server/backend/tests/ci.env`** (committed placeholders). **Locally**, use your **`server/backend/.env`**; to mimic CI:

```powershell
$env:CI = "true"
$env:PYTHONPATH = "."
uv run --directory server/backend pytest tests -q
```

**Integration tests:** db-service tests that need a real Postgres pool **skip** unless **`POSTGRES_HOST`** (and related vars) are set — see `server/db-service/tests/conftest.py`. Tests that need **Azurite** or the **pptx-renderer** sidecar **skip** when those endpoints are unreachable.

---

## Lint and format (Ruff)

From the repo root (after **`uv sync --group dev`**):

```bash
make format-check
make lint
# or:
uv run ruff format --check server tempslide
uv run ruff check server tempslide
```

Auto-fix locally (not what CI runs):

```bash
uv run ruff format server tempslide
uv run ruff check server tempslide --fix
```

---

## Run the same checks as CI (locally)

Rough parity with **`.github/workflows/ci.yml`**:

```bash
uv sync --group dev --frozen
uv lock --check
uv run ruff format --check server tempslide
uv run ruff check server tempslide
export CI=true
export PYTHONPATH=.
uv run --directory server/libs/pptx_master pytest tests -q
uv run --directory server/db-service pytest tests -q
uv run --directory server/backend pytest tests -q
npm ci --prefix client/app && npm ci --prefix client/admin
npm test --prefix client/app --silent
npm test --prefix client/admin --silent
```

**PowerShell:**

```powershell
uv sync --group dev --frozen
uv lock --check
uv run ruff format --check server tempslide
uv run ruff check server tempslide
$env:CI = "true"
$env:PYTHONPATH = "."
uv run --directory server/libs/pptx_master pytest tests -q
uv run --directory server/db-service pytest tests -q
uv run --directory server/backend pytest tests -q
npm ci --prefix client/app; npm ci --prefix client/admin
npm test --prefix client/app --silent
npm test --prefix client/admin --silent
```

**Docker image** (parity with **`.github/workflows/docker-build.yml`**):

```bash
docker build -f server/pptx-renderer/Dockerfile -t tempslide-pptx-renderer:local .
```

---

## GitHub Actions (what runs in CI)

Triggers: **pull requests** (any branch) and **pushes** to **`main`** or **`develop`**.  
Concurrency: **in-progress runs for the same branch/workflow are cancelled** when a new push arrives.

### `ci.yml` — two jobs

1. **`python`** (Ubuntu, **`CI=true`** for the whole job)
   - Checkout
   - **uv** `0.11.8` (cached)
   - **`uv python install`** (uses **`.python-version`**)
   - **`uv sync --group dev --frozen`**
   - **`uv lock --check`**
   - **`uv run ruff format --check server tempslide`**
   - **`uv run ruff check server tempslide`**
   - **pytest:** `server/libs/pptx_master`, `server/db-service`, `server/backend` (each via **`uv run --directory …`**)

2. **`frontend`** (Ubuntu, **Node 22**)
   - **`npm ci`** in `client/app` and `client/admin`
   - **`npm test`** (Vitest) for both

There is **no** mypy/pyright job and **no** coverage upload to third-party services.

### `docker-build.yml`

- **Docker Buildx** build of **`pptx-renderer`** from repo root (**`context: .`**, **`server/pptx-renderer/Dockerfile`**).
- **No image push** to a registry (build-only).

---

## Azure Dev Persistence

Temp-Slide is not deployed yet, but its dev persistence layer is defined under
`infra/` for the shared Azure dev subscription. The IaC provisions a private
PostgreSQL Flexible Server for `server/db-service` and a private Azure Managed
Redis cache that remains advisory; Postgres is the source of truth. It also
defines the private `sttempslidelogsdev` storage account, `logs` blob container,
blob private endpoint, managed identity, and container RBAC needed for Azure log
storage. Cloud persistence uses private networking and Microsoft Entra /
managed identity where the runtime supports it. See `infra/README.md` for the
deployment, private DNS, storage smoke-test, and runtime logging settings.

---

## PPTX Export

The app now exposes two PowerPoint export paths from the project header:

- **Export** keeps the existing backend-assisted flow. The backend reads the
  stored slide HTML, converts each slide to a `pptxgenjs` JSON spec with an LLM,
  streams that spec to the browser, and the browser downloads an editable
  `.pptx`.
- **DOM Export** is experimental. It uses `llm-dom-to-pptx` in the browser to
  render each already-loaded slide offscreen at `960x540` and export from the
  live DOM without a backend call or per-slide LLM conversion.

Use both buttons to compare fidelity and editability before promoting the DOM
engine. The DOM path is browser-only and depends on what the package can infer
from computed styles; complex CSS, fonts, SVGs, and unsupported layout features
may still differ from the slide preview. The agent-triggered `ExportDeck` tool
continues to use the existing backend-assisted export path.

`llm-dom-to-pptx@1.2.7` declares an older `pptxgenjs@^3.12.0` peer range while
this app uses `pptxgenjs@^4.0.1`, so `client/app/.npmrc` enables
`legacy-peer-deps` for the app install.
