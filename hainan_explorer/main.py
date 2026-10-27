"""FastAPI application factory and local server entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .pipelines import register_handlers
from .services.context import AppContext
from .services.jobs import JobService

log = logging.getLogger(__name__)
UI_DIR = Path(__file__).resolve().parent / "ui"


def create_app(ctx: AppContext | None = None, *, start_worker: bool = True) -> FastAPI:
    ctx = ctx or AppContext()
    jobs = JobService(ctx)
    register_handlers(jobs)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_worker:
            jobs.start_worker()
        yield
        jobs.stop_worker()

    app = FastAPI(title="Hainan Explorer", version=__import__("hainan_explorer").__version__, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.ctx = ctx
    app.state.jobs = jobs
    app.include_router(router)

    app.mount("/media/images", StaticFiles(directory=str(ctx.config.images_dir)), name="images")
    app.mount("/media/thumbnails", StaticFiles(directory=str(ctx.config.thumbnails_dir)), name="thumbnails")
    app.mount("/static", StaticFiles(directory=str(UI_DIR / "static")), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        index_path = UI_DIR / "index.html"
        if not index_path.is_file():
            raise HTTPException(404, "UI not built")
        return FileResponse(index_path)

    return app


def run(host: str | None = None, port: int | None = None) -> None:
    import uvicorn

    ctx = AppContext()
    app = create_app(ctx)
    host = host or ctx.config.host
    port = port or ctx.config.port
    if host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("Binding to %s exposes the app beyond this machine; make sure that is intended.", host)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run()
