"""Starting, reading and deleting export jobs: the one place the API and the HTML pages share."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from fastapi import UploadFile

from ..export import Options
from ..profile import ProfileError, check_margins, check_pattern, check_units
from ..raster import PNG_QUALITY, THUMB_BOX
from .jobs import Exporter, JobBusy, JobState, JobStore, Planner, run_job
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
        self.options = Options(thumb_box=THUMB_BOX)  # the page shows a preview of each sheet
        self.pool = ThreadPoolExecutor(max_workers=settings.max_concurrent_jobs, thread_name_prefix="job")

    async def start(self, file: UploadFile, images: str = "none", request: dict | None = None) -> JobState:
        """Save an upload and queue its export. The export runs in the background.

        `images` asks for PNG images next to the PDFs: none, standard (150 dpi) or 2x (300 dpi).
        `request` holds settings the person gave (see `settings_request`); the rest is worked out.
        """
        if images not in ("none", *PNG_QUALITY):
            raise JobError(400, "bad_images", f"images must be none, {', '.join(PNG_QUALITY)}.")
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
            state = await asyncio.to_thread(self.store.create, name, write_upload, images, request)
        except _TooLarge:
            mb = self.settings.max_upload_mb
            raise JobError(413, "too_large", f"The file is larger than {mb} MB.", mb=mb) from None
        self._queue(state.id)
        return state

    def rerun(self, job_id: str, request: dict) -> JobState:
        """Export a finished job again with other settings, from the drawing already uploaded."""
        try:
            state = self.store.reset(job_id, request)
        except KeyError:
            raise JobError(
                404, "not_found", "Not found. Jobs are deleted after a while; upload the drawing again."
            ) from None
        except JobBusy:
            raise JobError(409, "busy", "The drawing is still being exported. Wait until it is done.") from None
        self._queue(state.id)
        return state

    def _queue(self, job_id: str) -> None:
        self.pool.submit(partial(run_job, self.store, job_id, self.options, self.planner, self.exporter))

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

    def output(self, job_id: str, file: str) -> Path:
        """A finished PDF, PNG or preview of the job."""
        try:
            return self.store.output_path(job_id, file)
        except KeyError:
            raise JobError(404, "not_found", "Not found.") from None

    def zip(self, job_id: str, only: list[int] | None = None) -> tuple[Path, str]:
        """The ZIP of all PDFs, or of the sheets at the positions in `only`, and the name to download it as."""
        try:
            state = self.store.load(job_id)
            path = self.store.zip_path(job_id, only)
        except KeyError:
            raise JobError(404, "not_found", "Not found, or not finished yet.") from None
        stem = Path(state.drawing).stem
        if only is None:
            return path, f"{stem} - PDF.zip"
        count = sum(1 for i in set(only) if 0 <= i < len(state.sheets) and state.sheets[i].status == "done")
        return path, f"{stem} - PDF ({count}).zip"

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


def settings_request(
    title_pattern: str | None = None,
    scale_pattern: str | None = None,
    units: str | None = None,
    margins: str | None = None,
) -> dict:
    """Settings from a form or an API call, checked. Empty fields are left to be worked out.

    `margins` is "left,bottom,right,top" in mm.
    """
    try:
        request: dict = {}
        if title_pattern and title_pattern.strip():
            request["title_pattern"] = check_pattern(title_pattern, "title")
        if scale_pattern and scale_pattern.strip():
            request["scale_pattern"] = check_pattern(scale_pattern, "scale")
        if units and units != "auto":
            request["units"] = check_units(units)
        if margins and margins.strip():
            try:
                values = [float(v) for v in margins.split(",")]
            except ValueError:
                values = []
            request["margins_mm"] = list(check_margins(values))
    except ProfileError as e:
        raise JobError(400, e.code, str(e)) from None
    return request


def urls(job_id: str) -> dict[str, str]:
    base = f"/api/jobs/{job_id}"
    return {"base": base, "zip": f"{base}/zip"}


def file_url(job_id: str, file: str) -> str:
    return f"/api/jobs/{job_id}/files/{file}"
