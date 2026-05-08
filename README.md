# Temp Slide

Local development setup for the Edwin slide generator stack.

## Local Services

This checkout uses the default local development ports:

- Postgres: `localhost:5432`
- Redis: `localhost:6379`
- DB service: `http://localhost:8001`
- Backend API: `http://localhost:8000`
- App frontend: `http://localhost:5173`
- Admin frontend: `http://localhost:5174`

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

The local `.env` files are ignored by git and live in:

- `server/backend/.env`
- `server/db-service/.env`
- `client/app/.env`
- `client/admin/.env`

The backend and DB service validate Azure AD tokens against Microsoft JWKS and
use `certifi` as the default CA bundle. If your network requires a custom CA,
start the services with `AZURE_CACERT_PATH` or `SSL_CERT_FILE` pointing to that
bundle. Authenticated DB-service requests also upsert the current Azure user
before writing user-scoped data such as projects.

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

## Install Dependencies

```bash
uv venv
uv pip install -e server/libs/langfuse_client -e server/libs/app_logger -e server/libs/llm_provider -e server/libs/doc_parser -e server/libs/databases -e server/db-service -e server/backend
npm install --prefix client/app
npm install --prefix client/admin
```

## Start Dependencies

```bash
docker compose up -d
```

If either container already exists, start it instead:

```bash
docker compose up -d
```

## Start The App

Run each command in a separate terminal:

```bash
cd server/db-service
../../.venv/bin/alembic upgrade head
PYTHONPATH=. ../../.venv/bin/uvicorn app.main:app --reload --port 8001
```

```bash
cd server/backend
PYTHONPATH=. ../../.venv/bin/uvicorn app.main:app --reload --port 8000
```

```bash
npm run dev --prefix client/app -- --host 127.0.0.1 --port 5173
```

```bash
npm run dev --prefix client/admin -- --host 127.0.0.1 --port 5174
```
