import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from core.auth import require_auth
from core.config import settings
from core.csrf import CSRFMiddleware
from core.database import engine
from core.queue import close_queue, get_all_queues, init_queue
from core.rate_limit import RateLimitMiddleware
from core.redis_client import close_redis, get_redis, init_redis
from core.version import __version__
from routers import (
    artists,
    auth,
    backups,
    collections,
    datasets,
    download,
    explorer,
    export,
    external,
    gallery_dl_admin,
    history,
    import_router,
    library,
    novels,
    opds,
    queue_admin,
    rss,
    scheduled_tasks,
    search,
    subscription_groups,
    subscriptions,
    system,
    tag,
    ws,
)
from routers import (
    dedup as dedup_router,
)
from routers import (
    logs as logs_router,
)
from routers import (
    plugins as plugins_router,
)
from routers import (
    saucenao as saucenao_router,
)
from routers import settings as settings_router
from routers import site_config as site_config_router
from routers import (
    users as users_router,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _verify_schema_current() -> None:
    """Fail fast unless the DB is migrated to this image's alembic head.

    Guards the distributed-deploy case where a stale/mismatched migrate step
    left the DB behind the app image's schema; the api process then crash-loops
    instead of serving on a stale schema.
    """
    from core.config import settings
    from core.schema_guard import assert_db_at_head

    await assert_db_at_head(settings.gdl_archive_dsn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Jyzrox API rev 2.0...")
    await _verify_schema_current()
    await init_redis()
    from core.log_handler import apply_log_level_from_redis, install_log_handler

    install_log_handler("api", extra_loggers=["uvicorn", "uvicorn.access"])
    level = await apply_log_level_from_redis("api")
    logger.info("Log handler installed, level=%s", level)
    await init_queue()
    logger.info("Redis + SAQ queue ready")
    from plugins import init_plugins

    await init_plugins()
    logger.info("Plugins initialized")
    from core.site_config import site_config_service

    await site_config_service.start_listener()
    logger.info("SiteConfigService listener started")
    # Mount browse routers dynamically from plugins
    from plugins.registry import plugin_registry

    _BROWSE_PREFIX_MAP = {"ehentai": "/api/eh", "pixiv": "/api/pixiv"}
    for sid, router in plugin_registry.get_browse_routers():
        prefix = _BROWSE_PREFIX_MAP.get(sid, f"/api/browse/{sid}")
        app.include_router(router, prefix=prefix)
        logger.info("Mounted browse router: %s → %s", sid, prefix)
    from services.memory_watch import memory_watch_loop

    memory_watch_task = asyncio.create_task(memory_watch_loop())
    yield
    logger.info("Shutting down...")
    memory_watch_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await memory_watch_task
    await site_config_service.stop_listener()
    await close_queue()
    from services.eh_client import shutdown_shared_clients as _shutdown_eh_clients
    from services.pixiv_client import shutdown_shared_pixiv_clients as _shutdown_pixiv_clients

    try:
        await _shutdown_eh_clients()
    except Exception:
        logger.exception("Error shutting down EH shared clients")
    try:
        await _shutdown_pixiv_clients()
    except Exception:
        logger.exception("Error shutting down Pixiv shared clients")
    await close_redis()
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Jyzrox API",
    version=__version__,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,  # served manually with auth below
)

# Mount swagger-ui static assets
app.mount("/api/docs/static", StaticFiles(directory="/app/static/swagger-ui"), name="swagger-static")


@app.get("/api/openapi.json", include_in_schema=False)
async def openapi_schema(_: dict = Depends(require_auth)):
    return JSONResponse(content=app.openapi())


@app.get("/api/docs", include_in_schema=False)
async def custom_swagger_ui(_: dict = Depends(require_auth)) -> HTMLResponse:
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
app.include_router(explorer.router, prefix="/api/explorer")
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
app.include_router(datasets.router, prefix="/api/datasets")
app.include_router(novels.router, prefix="/api/novels")
app.include_router(opds.router, prefix="/opds")
app.include_router(scheduled_tasks.router, prefix="/api/scheduled-tasks")
app.include_router(subscriptions.router, prefix="/api/subscriptions")
app.include_router(subscription_groups.router, prefix="/api/subscription-groups")
app.include_router(dedup_router.router, prefix="/api/dedup")
app.include_router(users_router.router, prefix="/api/users")
app.include_router(rss.router, prefix="/api/rss")
app.include_router(logs_router.router, prefix="/api/logs")
app.include_router(backups.router, prefix="/api/admin/backups")
app.include_router(gallery_dl_admin.router, prefix="/api/admin/gallery-dl")
app.include_router(site_config_router.router, prefix="/api/admin/sites")
app.include_router(queue_admin.router, prefix="/api/admin/queue")
app.include_router(saucenao_router.router, prefix="/api/saucenao")


@app.get("/api/health")
async def health():
    """Lightweight liveness probe."""
    return {"status": "ok"}


@app.get("/api/ready")
async def ready():
    """Readiness probe that verifies dependencies required to serve traffic."""
    checks: dict[str, bool] = {}
    details: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as exc:
        checks["database"] = False
        details["database"] = str(exc)

    try:
        await get_redis().ping()
        checks["redis"] = True
    except Exception as exc:
        checks["redis"] = False
        details["redis"] = str(exc)

    try:
        queues = get_all_queues()
        checks["queue"] = bool(queues)
        if not queues:
            details["queue"] = "no initialized queues"
    except Exception as exc:
        checks["queue"] = False
        details["queue"] = str(exc)

    for name, path in {
        "data_gallery": settings.data_gallery_path,
        "data_cas": settings.data_cas_path,
        "data_thumbs": settings.data_thumbs_path,
    }.items():
        exists = os.path.isdir(path)
        checks[name] = exists
        if not exists:
            details[name] = f"{path} is not a directory"

    is_ready = all(checks.values())
    payload = {"status": "ok" if is_ready else "degraded", "checks": checks}
    if details:
        payload["details"] = details
    return JSONResponse(
        status_code=status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload,
    )


class _HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return '"GET /api/health' not in msg and '"GET /api/ready' not in msg


logging.getLogger("uvicorn.access").addFilter(_HealthCheckFilter())
