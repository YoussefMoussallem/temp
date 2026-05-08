"""
Backend service entrypoint.

This module builds the FastAPI application that the frontend and other
services talk to. Two routers are mounted under `/api`:

  - agent_router      -> chat / agent endpoints (LLM, planning, slides)
  - db_router         -> thin proxy to the separate db-service

Persistent state (users, projects, conversations, messages, usage) lives in
the db-service; this backend is stateless and calls db-service over HTTP.

Run with:
    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app_logger import get_logger

from app.config import get_settings
from app.bridges.logging_bridge import init_logging
from app.bridges.langfuse_bridge import init_langfuse
from app.middleware import (
    RequestContextMiddleware,
    register_exception_handlers,
    register_rate_limiting,
)
from app.agent.services.mcp.config import load_config as load_mcp_config
from app.agent.services.mcp.connection_manager import (
    McpConnectionManager,
    set_manager as set_mcp_manager,
)
from app.agent.router import router as agent_router
from app.db.router import router as db_router

logger = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Boot and tear down process-wide resources.

    On startup we dial every MCP server listed in
    the MCP config and stash the connection manager in a module-level slot
    so request handlers can reach it via `get_manager()`. A bad MCP config
    must not prevent the API from starting, so load failures are logged and
    we fall back to an empty config (no MCP tools available).

    On shutdown we close every MCP connection and clear the global slot.
    """
    try:
        configs = load_mcp_config()
    except Exception as e:
        configs = []
        logger.exception(f"MCP config load failed: {e}")

    mgr = McpConnectionManager(configs)
    await mgr.start()
    set_mcp_manager(mgr)
    try:
        yield
    finally:
        await mgr.shutdown()
        set_mcp_manager(None)


def create_app() -> FastAPI:
    init_logging()
    init_langfuse()
    settings = get_settings()

    app = FastAPI(title=settings.app.name, version="0.1.0", lifespan=_lifespan)

    # Middleware order matters. Starlette wraps in reverse of add order:
    # the *last* `add_middleware` call ends up *outermost*. We want the
    # request flow to be:
    #
    #   RequestContext (outermost) -> CORS -> RateLimit -> app
    #
    # so the access log captures the post-CORS final status, and CORS
    # headers are attached to 429 responses (browsers can't read a 429
    # without them). That means we add innermost first.
    register_rate_limiting(app)  # adds SlowAPIMiddleware (innermost)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)  # outermost

    # Catch-all for unhandled Exceptions raised before the response
    # starts. HTTPException / validation errors / SlowAPI's
    # RateLimitExceeded keep their own default handlers.
    register_exception_handlers(app)

    app.include_router(agent_router, prefix="/api")
    app.include_router(db_router, prefix="/api")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    logger.info("Edwin starting up")
    return app

app = create_app()
