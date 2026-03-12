import logging
import os
from contextlib import asynccontextmanager

from core.compat import patch_asyncio_for_314
patch_asyncio_for_314()

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from core.config import settings
from core.csrf import CSRFMiddleware
from core.rate_limit import RateLimitMiddleware
from core.database import engine
from core.redis_client import close_redis, init_redis
from routers import (
    artists,
    auth,
    collections,
    dedup as dedup_router,
    download,
    export,
    external,
    history,
    import_router,
    library,
    opds,
    plugins as plugins_router,
    scheduled_tasks,
    search,
    subscriptions,
    system,
    tag,
    ws,
)
from routers import settings as settings_router

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Jyzrox API rev 2.0...")
    await init_redis()
    app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    logger.info("Redis + ARQ pool ready")
    from plugins import init_plugins
    await init_plugins()
    logger.info("Plugins initialized")
    # Mount browse routers dynamically from plugins
    from plugins.registry import plugin_registry
    _BROWSE_PREFIX_MAP = {"ehentai": "/api/eh", "pixiv": "/api/pixiv"}
    for sid, router in plugin_registry.get_browse_routers():
        prefix = _BROWSE_PREFIX_MAP.get(sid, f"/api/browse/{sid}")
        app.include_router(router, prefix=prefix)
        logger.info("Mounted browse router: %s → %s", sid, prefix)
    yield
    logger.info("Shutting down...")
    await app.state.arq.aclose()
    await close_redis()
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Jyzrox API",
    version="0.1",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

# Mount swagger-ui static assets
app.mount("/api/docs/static", StaticFiles(directory="/app/static/swagger-ui"), name="swagger-static")

@app.get("/api/docs", include_in_schema=False)
async def custom_swagger_ui() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url="/api/openapi.json",
        title="Jyzrox API",
        swagger_js_url="/api/docs/static/swagger-ui-bundle.js",
        swagger_css_url="/api/docs/static/swagger-ui.css",
    )

# CORS: restrict to configured origin, or same-origin only
_cors_origins: list[str] = []
if settings.cors_origin:
    _cors_origins = [o.strip() for o in settings.cors_origin.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)
app.add_middleware(CSRFMiddleware)
app.add_middleware(RateLimitMiddleware)

app.include_router(auth.router, prefix="/api/auth")
app.include_router(system.router, prefix="/api/system")
app.include_router(library.router, prefix="/api/library")
app.include_router(download.router, prefix="/api/download")
app.include_router(settings_router.router, prefix="/api/settings")
app.include_router(ws.router, prefix="/api")

# rev 2.0 new routers
app.include_router(search.router, prefix="/api/search")
app.include_router(tag.router, prefix="/api/tags")
app.include_router(import_router.router, prefix="/api/import")
app.include_router(export.router, prefix="/api/export")
app.include_router(external.router, prefix="/api/external/v1")
app.include_router(history.router, prefix="/api/history")
app.include_router(plugins_router.router, prefix="/api/plugins")
app.include_router(artists.router, prefix="/api/artists")
app.include_router(collections.router, prefix="/api/collections")
app.include_router(opds.router, prefix="/opds")
app.include_router(scheduled_tasks.router, prefix="/api/scheduled-tasks")
app.include_router(subscriptions.router, prefix="/api/subscriptions")
app.include_router(dedup_router.router, prefix="/api/dedup")


@app.get("/api/health")
async def health():
    """Lightweight liveness probe."""
    return {"status": "ok"}
