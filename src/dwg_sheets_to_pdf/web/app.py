"""The web app: upload a drawing, watch its sheets export, download the PDFs."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import secrets
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from .. import __version__
from ..cadcraft import CadCraft
from ..export import Options, export, plan
from .jobs import Exporter, JobStore, Planner, run_job
from .settings import Settings

ALLOWED_SUFFIXES = (".dwg", ".dxf")
_CHUNK = 1024 * 1024


class UploadTooLarge(Exception):
    pass


def create_app(
    settings: Settings | None = None,
    planner: Planner | None = None,
    exporter: Exporter | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    store = JobStore(settings.work_dir, settings.job_ttl_minutes * 60)
    options = Options()

    if planner is None or exporter is None:
        cad = CadCraft(settings.cadcraft)  # fails at start-up, not on the first upload, if CADCraft is missing
        planner = planner or (lambda drawing, out_dir, opts, stem: plan(cad, drawing, out_dir, opts, stem))
        exporter = exporter or (
            lambda p, opts, on_done: export(cad, p, opts, workers=settings.export_workers, on_done=on_done)
        )

    jobs_pool = ThreadPoolExecutor(max_workers=settings.max_concurrent_jobs, thread_name_prefix="job")

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
            jobs_pool.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="DWG Sheets to PDF", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def require_password(request: Request, call_next):
        if settings.password and request.url.path != "/healthz" and not _authorized(request, settings.password):
            return Response(
                "Password required",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="DWG Sheets to PDF", charset="UTF-8"'},
            )
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        html = files("dwg_sheets_to_pdf.web").joinpath("static/index.html").read_text(encoding="utf-8")
        return html.replace("{{MAX_UPLOAD_MB}}", str(settings.max_upload_mb)).replace(
            "{{TTL_MINUTES}}", str(settings.job_ttl_minutes)
        )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.post("/api/jobs", status_code=202)
    async def create_job(file: UploadFile) -> JSONResponse:
        name = Path(file.filename or "").name
        if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(400, "Upload a .dwg or .dxf file.")
        limit = settings.max_upload_mb * 1024 * 1024

        def write_upload(dest: Path) -> None:
            size = 0
            with dest.open("wb") as out:
                while chunk := file.file.read(_CHUNK):
                    size += len(chunk)
                    if size > limit:
                        raise UploadTooLarge
                    out.write(chunk)
            if size == 0:
                raise HTTPException(400, "The file is empty.")

        try:
            state = await asyncio.to_thread(store.create, name, write_upload)
        except UploadTooLarge:
            raise HTTPException(413, f"The file is larger than {settings.max_upload_mb} MB.") from None
        jobs_pool.submit(partial(run_job, store, state.id, options, planner, exporter))
        return JSONResponse(_public(state.to_json()), status_code=202)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        return _public(_load(store, job_id).to_json())

    @app.delete("/api/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str) -> Response:
        _load(store, job_id)
        store.delete(job_id)
        return Response(status_code=204)

    @app.get("/api/jobs/{job_id}/pdf/{file}")
    def get_pdf(job_id: str, file: str, download: bool = False) -> FileResponse:
        try:
            path = store.pdf_path(job_id, file)
        except KeyError:
            raise HTTPException(404, "Not found.") from None
        disposition = "attachment" if download else "inline"
        return FileResponse(path, media_type="application/pdf", filename=file, content_disposition_type=disposition)

    @app.get("/api/jobs/{job_id}/zip")
    def get_zip(job_id: str) -> FileResponse:
        try:
            state = store.load(job_id)
            path = store.zip_path(job_id)
        except KeyError:
            raise HTTPException(404, "Not found, or not finished yet.") from None
        return FileResponse(path, media_type="application/zip", filename=f"{Path(state.drawing).stem} - PDF.zip")

    app.state.store = store
    return app


def _load(store: JobStore, job_id: str):
    try:
        return store.load(job_id)
    except KeyError:
        raise HTTPException(404, "Not found. Jobs are deleted after a while; upload the drawing again.") from None


def _public(job: dict) -> dict:
    """Job state for the browser, with download links."""
    base = f"/api/jobs/{job['id']}"
    for s in job["sheets"]:
        s["url"] = f"{base}/pdf/{s['file']}" if s["status"] == "done" else None
    job["zip_url"] = f"{base}/zip" if job["status"] == "done" else None
    return job


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
        "dwg_sheets_to_pdf.web.app:create_app",
        factory=True,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
