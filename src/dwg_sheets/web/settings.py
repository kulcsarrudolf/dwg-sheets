"""Web app settings, read from environment variables so the same image runs anywhere."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    work_dir: Path
    max_upload_mb: int = 100
    job_ttl_minutes: int = 30
    max_concurrent_jobs: int = 2
    export_workers: int = 4
    cadcraft: str = "cadcraft-cli"
    # When set, every request needs HTTP Basic auth with this password (any user name).
    password: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        work_dir = Path(env.get("WORK_DIR") or Path(tempfile.gettempdir()) / "dwg-sheets-jobs")
        return cls(
            work_dir=work_dir,
            max_upload_mb=int(env.get("MAX_UPLOAD_MB", cls.max_upload_mb)),
            job_ttl_minutes=int(env.get("JOB_TTL_MINUTES", cls.job_ttl_minutes)),
            max_concurrent_jobs=int(env.get("MAX_CONCURRENT_JOBS", cls.max_concurrent_jobs)),
            export_workers=int(env.get("EXPORT_WORKERS", cls.export_workers)),
            cadcraft=env.get("CADCRAFT_CLI", cls.cadcraft),
            password=env.get("APP_PASSWORD") or None,
        )
