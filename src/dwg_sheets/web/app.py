"""The web app: upload a drawing, watch its sheets export, download the PDFs."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import mimetypes
import secrets
from collections.abc import AsyncIterator
from importlib.resources import files

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..cadcraft import CadCraft
from ..export import export, plan
from .api import api_router
from .jobs import Exporter, JobStore, Planner
from .service import JobError, JobService
from .settings import Settings
from .views import views_router

mimetypes.add_type("font/woff2", ".woff2")  # slim images have no system MIME table for it


def create_app(
    settings: Settings | None = None,
    planner: Planner | None = None,
    exporter: Exporter | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    store = JobStore(settings.work_dir, settings.job_ttl_minutes * 60)

    if planner is None or exporter is None:
        cad = CadCraft(settings.cadcraft)  # fails at start-up, not on the first upload, if CADCraft is missing
        planner = planner or (lambda drawing, out_dir, opts, stem: plan(cad, drawing, out_dir, opts, stem))
        exporter = exporter or (
            lambda p, opts, on_done: export(cad, p, opts, workers=settings.export_workers, on_done=on_done)
        )
    service = JobService(settings, store, planner, exporter)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store.purge_expired()

        async def purge_loop() -> None:
            while True:
                await asyncio.sleep(60)
                await asyncio.to_thread(store.purge_expired)

        task = asyncio.create_task(purge_loop())
        try:
            yield
        finally:
            task.cancel()
            service.shutdown()

    app = FastAPI(title="DWG Sheets", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def require_password(request: Request, call_next):
        if settings.password and request.url.path != "/healthz" and not _authorized(request, settings.password):
            return Response(
                "Password required",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="DWG Sheets", charset="UTF-8"'},
            )
        return await call_next(request)

    @app.exception_handler(JobError)
    async def job_error(request: Request, e: JobError) -> JSONResponse:
        return JSONResponse(
            {"detail": {"code": e.code, "message": e.message, "params": e.params}}, status_code=e.status
        )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    static_dir = files("dwg_sheets.web").joinpath("static")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:  # browsers ask for it even when the page names another icon
        return FileResponse(str(static_dir.joinpath("icon.svg")), media_type="image/svg+xml")

    app.include_router(api_router(service))
    app.include_router(
        views_router(
            service,
            {"max_upload_mb": settings.max_upload_mb, "ttl_minutes": settings.job_ttl_minutes, "version": __version__},
        )
    )
    app.state.store = store
    return app


def _authorized(request: Request, password: str) -> bool:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        _, _, given = base64.b64decode(value).decode("utf-8").partition(":")
    except ValueError:
        return False
    return secrets.compare_digest(given.encode(), password.encode())


def main() -> None:
    """Run the web server. Reads HOST and PORT, as container services expect."""
    import os

    import uvicorn

    uvicorn.run(
        "dwg_sheets.web.app:create_app",
        factory=True,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
