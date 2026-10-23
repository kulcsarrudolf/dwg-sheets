"""Starting, reading and deleting export jobs: the one place the API and the HTML pages share."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from fastapi import UploadFile

from ..export import Options
from .jobs import Exporter, JobState, JobStore, Planner, run_job
from .settings import Settings

ALLOWED_SUFFIXES = (".dwg", ".dxf")
_CHUNK = 1024 * 1024


class JobError(Exception):
    """A request the job service refuses, with a stable code the pages translate."""

    def __init__(self, status: int, code: str, message: str, **params) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.params = params


class _TooLarge(Exception):
    pass


class JobService:
    def __init__(self, settings: Settings, store: JobStore, planner: Planner, exporter: Exporter) -> None:
        self.settings = settings
        self.store = store
        self.planner = planner
        self.exporter = exporter
        self.options = Options()
        self.pool = ThreadPoolExecutor(max_workers=settings.max_concurrent_jobs, thread_name_prefix="job")

    async def start(self, file: UploadFile) -> JobState:
        """Save an upload and queue its export. The export runs in the background."""
        name = Path(file.filename or "").name
        if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise JobError(400, "bad_type", "Upload a .dwg or .dxf file.")
        limit = self.settings.max_upload_mb * 1024 * 1024

        def write_upload(dest: Path) -> None:
            size = 0
            with dest.open("wb") as out:
                while chunk := file.file.read(_CHUNK):
                    size += len(chunk)
                    if size > limit:
                        raise _TooLarge
                    out.write(chunk)
            if size == 0:
                raise JobError(400, "empty", "The file is empty.")

        try:
            state = await asyncio.to_thread(self.store.create, name, write_upload)
        except _TooLarge:
            mb = self.settings.max_upload_mb
            raise JobError(413, "too_large", f"The file is larger than {mb} MB.", mb=mb) from None
        self.pool.submit(partial(run_job, self.store, state.id, self.options, self.planner, self.exporter))
        return state

    def get(self, job_id: str) -> JobState:
        try:
            return self.store.load(job_id)
        except KeyError:
            raise JobError(
                404, "not_found", "Not found. Jobs are deleted after a while; upload the drawing again."
            ) from None

    def delete(self, job_id: str) -> None:
        self.get(job_id)
        self.store.delete(job_id)

    def pdf(self, job_id: str, file: str) -> Path:
        try:
            return self.store.pdf_path(job_id, file)
        except KeyError:
            raise JobError(404, "not_found", "Not found.") from None

    def zip(self, job_id: str) -> tuple[Path, str]:
        """The ZIP of all PDFs and the name to download it as."""
        try:
            state = self.store.load(job_id)
            return self.store.zip_path(job_id), f"{Path(state.drawing).stem} - PDF.zip"
        except KeyError:
            raise JobError(404, "not_found", "Not found, or not finished yet.") from None

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


def urls(job_id: str) -> dict[str, str]:
    base = f"/api/jobs/{job_id}"
    return {"base": base, "zip": f"{base}/zip"}


def pdf_url(job_id: str, file: str) -> str:
    return f"/api/jobs/{job_id}/pdf/{file}"
