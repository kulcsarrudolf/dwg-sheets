"""JSON API, for scripts and other clients. Downloads also live here; the pages link to them."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from .jobs import JobState
from .service import JobService, file_url, urls


def api_router(service: JobService) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/jobs", status_code=202)
    async def create_job(file: UploadFile, images: Annotated[str, Form()] = "none") -> JSONResponse:
        return JSONResponse(_public(await service.start(file, images)), status_code=202)

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        return _public(service.get(job_id))

    @router.delete("/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str) -> Response:
        service.delete(job_id)
        return Response(status_code=204)

    @router.get("/jobs/{job_id}/files/{file}")
    def get_file(job_id: str, file: str, download: bool = False) -> FileResponse:
        path = service.output(job_id, file)
        return FileResponse(
            path,
            media_type=_MEDIA_TYPES.get(path.suffix, "application/pdf"),
            filename=file,
            content_disposition_type="attachment" if download else "inline",
            # A job's files never change once written, so the browser can keep them while the page refreshes.
            headers={"Cache-Control": "private, max-age=3600, immutable"},
        )

    @router.get("/jobs/{job_id}/zip")
    def get_zip(job_id: str, sheet: Annotated[list[int] | None, Query()] = None) -> FileResponse:
        """Every sheet, or only the ones given by their position in the job's list: ?sheet=0&sheet=3."""
        path, name = service.zip(job_id, sheet)
        return FileResponse(path, media_type="application/zip", filename=name)

    return router


_MEDIA_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".webp": "image/webp"}


def _public(state: JobState) -> dict:
    """Job state with download links."""
    job = state.to_json()
    for s in job["sheets"]:
        done = s["status"] == "done"
        s["url"] = file_url(job["id"], s["file"]) if done else None
        s["png_url"] = file_url(job["id"], s["png"]) if done and s["png"] else None
        s["thumb_url"] = file_url(job["id"], s["thumb"]) if done and s["thumb"] else None
    job["zip_url"] = urls(job["id"])["zip"] if job["status"] == "done" else None
    return job
