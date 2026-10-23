"""JSON API, for scripts and other clients. Downloads also live here; the pages link to them."""

from __future__ import annotations

from fastapi import APIRouter, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from .jobs import JobState
from .service import JobService, pdf_url, urls


def api_router(service: JobService) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/jobs", status_code=202)
    async def create_job(file: UploadFile) -> JSONResponse:
        return JSONResponse(_public(await service.start(file)), status_code=202)

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        return _public(service.get(job_id))

    @router.delete("/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str) -> Response:
        service.delete(job_id)
        return Response(status_code=204)

    @router.get("/jobs/{job_id}/pdf/{file}")
    def get_pdf(job_id: str, file: str, download: bool = False) -> FileResponse:
        return FileResponse(
            service.pdf(job_id, file),
            media_type="application/pdf",
            filename=file,
            content_disposition_type="attachment" if download else "inline",
        )

    @router.get("/jobs/{job_id}/zip")
    def get_zip(job_id: str) -> FileResponse:
        path, name = service.zip(job_id)
        return FileResponse(path, media_type="application/zip", filename=name)

    return router


def _public(state: JobState) -> dict:
    """Job state with download links."""
    job = state.to_json()
    for s in job["sheets"]:
        s["url"] = pdf_url(job["id"], s["file"]) if s["status"] == "done" else None
    job["zip_url"] = urls(job["id"])["zip"] if job["status"] == "done" else None
    return job
