"""Edwin DB Service — standalone microservice for users, usage, and auth."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db, close_db
from app.middleware import register_rate_limiting
from app.routers.auth import router as auth_router
from app.routers.users import router as users_router
from app.routers.usage import router as usage_router
from app.routers.admin import router as admin_router
from app.routers.settings import router as settings_router
from app.routers.slides import router as slides_router
from app.routers.projects import router as projects_router
from app.routers.messages import router as messages_router
from app.routers.conversations import router as conversations_router
from app.routers.memories import router as memories_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


def create_app() -> FastAPI:
    app = FastAPI(title="Edwin DB Service", version="0.1.0", lifespan=lifespan)

    # Middleware order: Starlette wraps in reverse, so the *last*
    # `add_middleware` call ends up *outermost*. We want CORS outermost
    # so 429 rate-limit responses still carry CORS headers (the browser
    # otherwise can't read them). Add SlowAPI first (innermost), CORS
    # second (outermost).
    register_rate_limiting(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router, prefix="/api")
    app.include_router(users_router, prefix="/api")
    app.include_router(usage_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(projects_router, prefix="/api")
    app.include_router(conversations_router, prefix="/api")
    app.include_router(messages_router, prefix="/api")
    app.include_router(slides_router, prefix="/api")
    app.include_router(memories_router, prefix="/api")

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "db-service"}

    return app


app = create_app()
