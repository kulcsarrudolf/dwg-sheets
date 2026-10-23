"""Stand-ins for CADCraft, and helpers shared by the web tests."""

import time
from pathlib import Path

from dwg_sheets_to_pdf.export import Plan, SheetResult
from dwg_sheets_to_pdf.sheets import Rect, Sheet, Skipped

PDF = b"%PDF-1.7 fake\n"


def fake_planner(names=("A13", "A14"), skipped=()):
    def planner(drawing: Path, out_dir: Path, options, stem: str) -> Plan:
        assert drawing.read_bytes().startswith(b"AC10")
        sheets = [Sheet(n, Rect(0, 0, 42, 29.7), 100.0, double=(i == 0)) for i, n in enumerate(names)]
        results = [
            SheetResult(n, 100.0, (420.0, 297.0), i == 0, out_dir / f"{stem} - {n}.pdf") for i, n in enumerate(names)
        ]
        return Plan(drawing, results, [Skipped(*s) for s in skipped], sheets)

    return planner


def fake_exporter(fail=()):
    def exporter(p: Plan, options, on_done):
        for r in p.results:
            if r.name in fail:
                r.error = "plot failed"
            else:
                r.file.parent.mkdir(parents=True, exist_ok=True)
                r.file.write_bytes(PDF)
            on_done(r)
        return p.results

    return exporter


def wait(client, job_id, **kw):
    """Poll the API until the job finishes."""
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}", **kw).json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")
