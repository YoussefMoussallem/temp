"""db-service test fixtures.

Three layers, scoped to keep cold-start under ~1s:

* **Pure unit** — no fixtures required. Reads/writes nothing.
* **HTTP** — FastAPI driven via ``httpx.AsyncClient`` against the
  in-process ASGI handler. No real server. Lands when routers do.
* **Integration** — real Postgres pool. Session-scoped so we pay the
  Entra token + connection cost once per ``pytest`` invocation.

Integration tests skip cleanly when no DB is reachable — fresh
checkouts and CI-without-secrets stay green. The skip message tells
the developer which env vars to set.

The ``tmp_project`` fixture cascades through ``ON DELETE CASCADE`` —
deleting the project drops every master / slide / message we created
under it, so tests don't leak data into each other.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import load_dotenv

# Source the service's .env once at collection time. Without this,
# integration tests that need ``POSTGRES_HOST`` would skip on a
# normal ``pytest`` invocation — pydantic-settings reads .env into
# its Settings class but never propagates to ``os.environ``, which
# is what our ``_have_db_env`` check inspects. Loading lazily here
# (and only here) keeps the production app untouched.
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
if _ENV_PATH.is_file():
    load_dotenv(_ENV_PATH, override=False)


def _have_db_env() -> bool:
    """Cheap check: do we have at least the host configured?"""
    return bool(os.environ.get("POSTGRES_HOST"))


@pytest.fixture(scope="session", autouse=True)
def _init_blob_client_for_tests() -> None:
    """Initialise the blob client once per test session.

    The FastAPI lifespan doesn't fire under ``httpx.ASGITransport``
    (it ships with ``lifespan="off"`` by default and turning it on
    introduces its own quirks across pytest-asyncio versions). Tests
    that drive the app via httpx need the blob client wired anyway —
    POST /masters with bytes calls upload_master_pptx().

    Side-effect: pin the connection string to Azurite, even if
    AZURE_BLOB_ACCOUNT_URL slipped into the test env. Tests must
    NEVER write to a real cloud account.
    """
    os.environ["AZURE_BLOB_CONNECTION_STRING"] = "UseDevelopmentStorage=true"
    os.environ.pop("AZURE_BLOB_ACCOUNT_URL", None)

    from app.storage import blob as blob_mod

    blob_mod._service_client = None  # noqa: SLF001 — re-init for the test
    blob_mod.init_blob_client()


@pytest_asyncio.fixture(scope="session")
async def pool() -> AsyncIterator:
    """Real asyncpg pool against the configured Postgres.

    Session-scoped: opening Entra-auth'd connections is several hundred
    ms each; per-test pools would dominate suite runtime. Tests must
    not rely on connection-local state (transaction isolation,
    SET LOCAL, etc.) bleeding between cases.
    """
    if not _have_db_env():
        pytest.skip(
            "POSTGRES_HOST not set — integration tests need DB env vars. "
            "Start the db-service .env or set POSTGRES_HOST manually."
        )

    from app.db import close_db, get_pool, init_db

    await init_db()
    p = await get_pool()
    yield p
    await close_db()


@pytest_asyncio.fixture
async def tmp_user(pool):
    """Create a throwaway user row and yield its azure_oid.

    Real masters require a project, real projects require a user.
    Rather than reuse the developer's actual user (which would leave
    test data scattered through their projects list), we mint one
    per session under a recognisable prefix and drop it at teardown.
    Cascades cover everything underneath.
    """
    oid = f"test-{uuid.uuid4().hex[:12]}"
    await pool.execute(
        "INSERT INTO users (azure_oid, email, display_name) VALUES ($1, $2, $3)",
        oid,
        f"{oid}@test.local",
        "pytest user",
    )
    yield oid
    await pool.execute("DELETE FROM users WHERE azure_oid = $1", oid)


@pytest_asyncio.fixture
async def http_client(pool, tmp_user) -> AsyncIterator:
    """In-process FastAPI client driven via httpx.AsyncClient.

    Auth is overridden to return ``tmp_user`` so every request looks
    authenticated as the throwaway user. ``require_project_access``
    is overridden too because it's a function dependency, not a
    typical Depends() — we replace it module-globally with a no-op
    that returns ``"owner"``. Tests that need to assert the access
    check itself (e.g. 403 paths) can re-stub it locally.

    The client is async because the FastAPI app is async; ``httpx``'s
    ASGI transport runs the app in-process so no real server is
    started.
    """
    import httpx

    from app.dependencies import CurrentUser, get_current_user
    from app.main import app
    from app.db.projects import access as access_mod

    fake_user = CurrentUser(
        user_id=tmp_user,
        email=f"{tmp_user}@test.local",
        display_name="pytest user",
        azure_oid=tmp_user,
    )

    async def _override_user():
        return fake_user

    # Bypass project-membership lookup — tests that want to exercise
    # the real check can re-replace this attribute inside the test.
    original_require = access_mod.require_project_access

    async def _override_access(*args, **kwargs):
        return "owner"

    access_mod.require_project_access = _override_access
    app.dependency_overrides[get_current_user] = _override_user

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Carry the test user through the request so the route's
        # ``access_mod.require_project_access`` import-time binding,
        # if any router cached it, still finds our override. Most
        # routers do ``await require_project_access(...)`` from the
        # module reference each call, so the patched attribute wins.
        yield client

    app.dependency_overrides.pop(get_current_user, None)
    access_mod.require_project_access = original_require


@pytest_asyncio.fixture
async def tmp_project(pool, tmp_user):
    """Create a throwaway project owned by ``tmp_user`` and yield it.

    Returns the row as a dict so tests don't have to import the
    Project dataclass — masters tests don't care about Project's
    fields, just its id.
    """
    row = await pool.fetchrow(
        """
        INSERT INTO projects (user_id, name, description)
        VALUES ($1, $2, $3)
        RETURNING id, user_id, name, description, active_master_id
        """,
        tmp_user,
        f"pytest-{uuid.uuid4().hex[:8]}",
        "ephemeral",
    )
    # project_members.INSERT is a separate table; tests don't query it
    # but the FK is required by some queries. Insert minimal owner row.
    await pool.execute(
        "INSERT INTO project_members (user_id, project_id, role) VALUES ($1, $2, 'owner')",
        tmp_user,
        row["id"],
    )
    yield dict(row)
    # Cascades drop members, masters, slides, conversations, messages.
    await pool.execute("DELETE FROM projects WHERE id = $1", row["id"])
