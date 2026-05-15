# Test + verify entry points for local dev.
#
# Goal: a single ``make verify`` that runs all four test suites in
# parallel and exits non-zero on any failure. Sub-15s on a happy path,
# under 30s with cold caches. CI will eventually call ``make verify``
# too — keep it self-contained (no env vars, no live services).
#
# Conventions:
#   * Each target prints its own banner so `make verify` output stays
#     legible when suites run in parallel.
#   * No service starts. Tests that need Postgres/Redis/Azurite must
#     mark themselves and skip when env vars aren't set.
#   * No ``cd && ...`` chained commands across targets — Make's ``-C``
#     keeps the working directory explicit.
#
# Python deps are managed from the repo root with ``uv`` (see README).

.PHONY: help verify test-backend test-db-service test-app test-admin test-py test-fe install install-runtime format-check lint test type-check

help:
	@echo "Targets:"
	@echo "  verify          run all test suites (run 'uv sync --group dev' first if the venv is new)"
	@echo "  format-check    ruff format --check (server + tempslide)"
	@echo "  lint            ruff check (server + tempslide)"
	@echo "  test            pytest backend + db-service (same as test-py)"
	@echo "  type-check      no-op (add mypy/pyright to dev deps when ready)"
	@echo "  test-py         pytest against backend + db-service (via uv run)"
	@echo "  test-fe         vitest against client/app + client/admin"
	@echo "  test-backend    pytest backend only"
	@echo "  test-db-service pytest db-service only"
	@echo "  test-app        vitest client/app only"
	@echo "  test-admin      vitest client/admin only"
	@echo "  install         uv sync --group dev (default dev environment)"
	@echo "  install-runtime uv sync --no-dev (Python runtime only, no test tools)"

# Run everything. Parallel via -j; suite failures halt with -k flag off
# so a single break still fails the build cleanly.
verify: test-py test-fe
	@echo ""
	@echo "✓ all suites passed"

format-check:
	uv run ruff format --check server tempslide

lint:
	uv run ruff check server tempslide

test: test-py

type-check:
	@echo "No Python type checker configured yet (mypy / pyright)."
	@exit 0

test-py: test-backend test-db-service

test-fe: test-app test-admin

test-backend:
	@echo "── pytest: backend ────────────────────────────────────────────"
	@cd server/backend && PYTHONPATH=. uv run pytest tests -q

test-db-service:
	@echo "── pytest: db-service ────────────────────────────────────────"
	@cd server/db-service && PYTHONPATH=. uv run pytest tests -q

test-app:
	@echo "── vitest: client/app ────────────────────────────────────────"
	@npm test --prefix client/app --silent

test-admin:
	@echo "── vitest: client/admin ──────────────────────────────────────"
	@npm test --prefix client/admin --silent

install:
	uv sync --group dev

install-runtime:
	uv sync --no-dev
