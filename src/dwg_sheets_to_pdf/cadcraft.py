"""Thin wrapper around the CADCraft command-line tool (`cadcraft-cli`)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class CadCraftError(RuntimeError):
    pass


class CadCraft:
    def __init__(self, executable: str = "cadcraft-cli") -> None:
        path = shutil.which(executable)
        if path is None:
            raise CadCraftError(
                f"`{executable}` was not found. Install the CADCraft command-line tool from "
                "https://github.com/storytold/cadcraft/releases and put it on your PATH, "
                "or pass --cadcraft PATH."
            )
        self.executable = path

    def run(self, drawing: Path, *commands: dict | str) -> list:
        """Open `drawing`, run each command in order, return each command's JSON result."""
        args = [self.executable, "run", str(drawing)]
        for c in commands:
            args += ["--cmd", c if isinstance(c, str) else _command(c)]
        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode != 0:
            raise CadCraftError((proc.stderr or proc.stdout).strip())
        return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]

    def polylines(self, drawing: Path) -> list[dict]:
        (result,) = self.run(drawing, {"id": "entities", "type": "Polyline", "limit": 10_000_000})
        return result["entities"]

    def texts(self, drawing: Path) -> list[dict]:
        (result,) = self.run(drawing, {"id": "texts", "limit": 10_000_000})
        return result["texts"]

    def export_pdf(
        self,
        drawing: Path,
        out: Path,
        window: tuple[float, float, float, float],
        mm_per_unit: float,
        page_mm: tuple[float, float],
    ) -> None:
        x0, y0, x1, y1 = window
        width, height = page_mm
        self.run(
            drawing,
            {
                "id": "exportpdf",
                "path": str(out),
                "layout": "Model",
                "plotArea": "window",
                "window": [[x0, y0], [x1, y1]],
                "scale": mm_per_unit,
                "center": True,
                "width": width,
                "height": height,
                # Without this CADCraft keeps a 5 mm printer margin and shrinks the sheet to
                # fit inside it. The page is the sheet frame, so it must reach the page edge.
                "margins": [0, 0, 0, 0],
                "landscape": width >= height,
            },
        )


def _command(c: dict) -> str:
    params = {k: v for k, v in c.items() if k != "id"}
    return f"{c['id']} {json.dumps(params)}"
