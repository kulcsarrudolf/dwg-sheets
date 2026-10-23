"""Export jobs: one uploaded drawing, its sheets, and the PDFs, kept in a private folder.

Each job lives in `<work_dir>/<job id>/`:
    input/<drawing>     the upload
    pdf/<sheet>.pdf     the exports
    job.json            the state the browser polls

The state file is the single source of truth, so the web process holds no job
state in memory. Jobs are deleted after their time to live, because drawings
carry client details.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from ..cadcraft import CadCraftError
from ..export import Options, Plan, SheetResult
from ..raster import PNG_QUALITY

JOB_ID = re.compile(r"^[0-9a-f]{32}$")


@dataclass
class SheetInfo:
    name: str
    scale: float
    page_mm: list[float]
    double: bool
    file: str  # file name inside pdf/
    status: str = "pending"  # pending | done | failed
    error: str | None = None
    label: str = ""  # unique: the number, with -1, -2, ... when several sheets share it
    png: str | None = None  # image file name inside pdf/, when images were asked for
    png_dpi: int | None = None


@dataclass
class JobState:
    id: str
    drawing: str
    created: float
    status: str = "queued"  # queued | reading | exporting | done | failed
    error: str | None = None  # English message, for API users
    # Stable id and values for the message, so the page can show it in the reader's language:
    # no_sheets, unreadable, partial {failed, total}, unexpected
    error_code: str | None = None
    error_params: dict = field(default_factory=dict)
    sheets: list[SheetInfo] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    duplicates: dict[str, int] = field(default_factory=dict)  # sheet numbers several sheets share
    images: str = "none"  # none | standard | 2x: PNG images next to the PDFs (see raster.PNG_QUALITY)

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> JobState:
        sheets = [SheetInfo(**s) for s in data.pop("sheets", [])]
        return cls(**data, sheets=sheets)


class JobStore:
    def __init__(self, root: Path, ttl_seconds: float) -> None:
        self.root = root
        self.ttl = ttl_seconds
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # Paths -----------------------------------------------------------------

    def dir(self, job_id: str) -> Path:
        if not JOB_ID.match(job_id):
            raise KeyError(job_id)
        return self.root / job_id

    def pdf_dir(self, job_id: str) -> Path:
        return self.dir(job_id) / "pdf"

    def output_path(self, job_id: str, file: str) -> Path:
        """A PDF or PNG of this job, only if the job lists it (so no path from the URL reaches the disk)."""
        state = self.load(job_id)
        if not any(file in (s.file, s.png) and s.status == "done" for s in state.sheets):
            raise KeyError(file)
        return self.pdf_dir(job_id) / file

    # State -----------------------------------------------------------------

    def create(self, drawing_name: str, write_upload: Callable[[Path], None], images: str = "none") -> JobState:
        job_id = uuid.uuid4().hex
        d = self.root / job_id
        (d / "input").mkdir(parents=True)
        try:
            write_upload(d / "input" / _safe_upload_name(drawing_name))
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise
        state = JobState(job_id, drawing_name, time.time(), images=images)
        self.save(state)
        return state

    def input_path(self, job_id: str) -> Path:
        (path,) = (self.dir(job_id) / "input").iterdir()
        return path

    def load(self, job_id: str) -> JobState:
        path = self.dir(job_id) / "job.json"
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            raise KeyError(job_id) from None
        return JobState.from_json(data)

    def save(self, state: JobState) -> None:
        d = self.dir(state.id)
        tmp = d / "job.json.tmp"
        with self._lock:
            tmp.write_text(json.dumps(state.to_json()))
            os.replace(tmp, d / "job.json")

    def delete(self, job_id: str) -> None:
        shutil.rmtree(self.dir(job_id), ignore_errors=True)

    def purge_expired(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        removed = 0
        for d in self.root.iterdir():
            if not (d.is_dir() and JOB_ID.match(d.name)):
                continue
            try:
                created = self.load(d.name).created
            except (KeyError, ValueError, TypeError):
                created = d.stat().st_mtime  # half-written job: fall back to the folder's age
            if now - created > self.ttl:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        return removed

    # Downloads -------------------------------------------------------------

    def zip_path(self, job_id: str) -> Path:
        """All exported PDFs (and images) in one ZIP, built once the job is done."""
        state = self.load(job_id)
        if state.status != "done":
            raise KeyError(job_id)
        path = self.dir(job_id) / "sheets.zip"
        if not path.exists():
            tmp = path.with_suffix(".zip.tmp")
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
                for s in state.sheets:
                    if s.status == "done":
                        for name in filter(None, (s.file, s.png)):
                            z.write(self.pdf_dir(job_id) / name, name)
            os.replace(tmp, path)
        return path


# The exporter is injected so tests can run without CADCraft.
Planner = Callable[[Path, Path, Options, str], Plan]
Exporter = Callable[[Plan, Options, Callable[[SheetResult], None]], list[SheetResult]]


def run_job(store: JobStore, job_id: str, options: Options, planner: Planner, exporter: Exporter) -> None:
    """Find and export the sheets of one job, saving progress to its state file as it goes."""
    state = store.load(job_id)
    try:
        state.status = "reading"
        store.save(state)
        drawing = store.input_path(job_id)
        stem = Path(state.drawing).stem
        options = replace(options, png_dpi=PNG_QUALITY.get(state.images))
        p = planner(drawing, store.pdf_dir(job_id), options, stem)
        state.sheets = [
            SheetInfo(
                r.name,
                r.scale,
                list(r.page_mm),
                r.double,
                r.file.name,
                label=r.label,
                png=r.png.name if r.png else None,
            )
            for r in p.results
        ]
        state.skipped = [{"name": s.name, "reason": s.reason, "code": s.code} for s in p.skipped]
        state.duplicates = dict(p.duplicates)
        if not p.results:
            state.status = "failed"
            state.error = "No sheets found. Each sheet needs a 'PL. NR.' title block inside a rectangular frame."
            state.error_code = "no_sheets"
            store.save(state)
            return
        state.status = "exporting"
        store.save(state)

        # Each result to its own row. Not by name or file: sheets can share a number.
        info_for = {id(r): info for r, info in zip(p.results, state.sheets, strict=True)}
        progress_lock = threading.Lock()  # sheets finish on several export threads

        def on_done(r: SheetResult) -> None:
            with progress_lock:
                info = info_for[id(r)]
                info.status = "done" if r.ok else "failed"
                info.error = r.error
                info.png_dpi = r.png_dpi
                store.save(state)

        exporter(p, options, on_done)
        failed = [s for s in state.sheets if s.status != "done"]
        state.status = "done" if len(failed) < len(state.sheets) else "failed"
        if failed:
            state.error = f"{len(failed)} of {len(state.sheets)} sheet(s) could not be exported."
            state.error_code = "partial"
            state.error_params = {"failed": len(failed), "total": len(state.sheets)}
    except CadCraftError as e:
        state.status = "failed"
        state.error = f"The drawing could not be read: {e}"
        state.error_code = "unreadable"
    except Exception as e:  # keep the job readable for the browser whatever went wrong
        state.status = "failed"
        state.error = f"Unexpected error: {e}"
        state.error_code = "unexpected"
    store.save(state)


def _safe_upload_name(name: str) -> str:
    base = Path(name).name
    suffix = Path(base).suffix.lower()
    return f"drawing{suffix}" if suffix in (".dwg", ".dxf") else "drawing"
