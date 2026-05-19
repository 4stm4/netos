from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.configurator.routes.targets import router as targets_router
from src.configurator.routes.packages import router as packages_router
from src.configurator.routes.profiles import router as profiles_router
from src.configurator.routes.builds import router as builds_router

UI_DIST = Path(__file__).parent / "ui" / "dist"

_NO_BUILD_HTML = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>netOS Configurator — build required</title>
  <style>
    body{background:#08080a;color:#ededee;font-family:system-ui,sans-serif;
         display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
    pre{background:#131317;border:1px solid #1d1d22;border-radius:8px;padding:1.5rem;
        font-size:14px;color:#f4f4f5}
    h1{color:#f59e0b}p{color:#b6b6bc}
  </style>
</head>
<body>
  <div>
    <h1>UI not built</h1>
    <p>Run the following command to build the frontend:</p>
    <pre>cd src/configurator/ui &amp;&amp; npm install &amp;&amp; npm run build</pre>
    <p>Then restart the server.</p>
  </div>
</body>
</html>
"""


def create_app() -> FastAPI:
    app = FastAPI(title="netOS Build Configurator", version="0.1.0")

    app.include_router(targets_router, prefix="/api")
    app.include_router(packages_router, prefix="/api")
    app.include_router(profiles_router, prefix="/api")
    app.include_router(builds_router, prefix="/api")

    if UI_DIST.exists():
        app.mount("/", StaticFiles(directory=str(UI_DIST), html=True), name="ui")
    else:
        @app.get("/", response_class=HTMLResponse)
        async def no_build():
            return HTMLResponse(content=_NO_BUILD_HTML)

    return app
