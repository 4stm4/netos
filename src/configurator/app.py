from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.configurator.routes.targets import router as targets_router
from src.configurator.routes.packages import router as packages_router
from src.configurator.routes.profiles import router as profiles_router
from src.configurator.routes.builds import router as builds_router
from src.configurator.routes.cache import router as cache_router
from src.configurator.routes.fs import router as fs_router
from src.configurator.routes.presets import router as presets_router
from src.configurator.routes.settings import router as settings_router, apply_saved_settings
from src.configurator.routes.kernel import router as kernel_router
from src.configurator.routes.kernel_catalog import router as kernel_catalog_router

_HERE = Path(__file__).parent
_INDEX_HTML = _HERE / "templates" / "index.html"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    apply_saved_settings()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="netOS Build Configurator", version="0.1.0", lifespan=_lifespan)

    app.include_router(targets_router, prefix="/api")
    app.include_router(packages_router, prefix="/api")
    app.include_router(profiles_router, prefix="/api")
    app.include_router(builds_router, prefix="/api")
    app.include_router(cache_router, prefix="/api")
    app.include_router(fs_router, prefix="/api")
    app.include_router(presets_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(kernel_router, prefix="/api")
    app.include_router(kernel_catalog_router, prefix="/api")

    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    @app.get("/")
    async def index():
        return HTMLResponse(content=_INDEX_HTML.read_text())

    return app
