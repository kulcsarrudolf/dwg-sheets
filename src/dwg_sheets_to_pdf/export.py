"""Find the sheets in a drawing and export each one to its own PDF.

Shared by the command line and the web app.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .cadcraft import CadCraft, CadCraftError
from .sheets import (
    DEFAULT_MARGINS_MM,
    DEFAULT_TITLE_PATTERN,
    Sheet,
    Skipped,
    duplicates,
    find_sheets,
    labels,
    rectangles,
    safe_filename,
)


@dataclass(frozen=True)
class Options:
    unit_mm: float = 1000.0  # drawing units are metres
    margins_mm: tuple[float, float, float, float] = DEFAULT_MARGINS_MM
    title_pattern: str = DEFAULT_TITLE_PATTERN


@dataclass
class SheetResult:
    name: str
    scale: float
    page_mm: tuple[float, float]
    double: bool
    file: Path
    error: str | None = None
    # Unique among the drawing's sheets: the number, with -1, -2, ... when several sheets share it.
    label: str = ""

    def __post_init__(self) -> None:
        self.label = self.label or self.name

    @property
    def ok(self) -> bool:
        return self.error is None

    def describe(self) -> str:
        w, h = self.page_mm
        kind = "double frame, outer line hidden" if self.double else "single frame, margins added"
        return f"{self.label}: 1:{self.scale:g}, {w:g} x {h:g} mm ({kind})"


@dataclass
class Plan:
    """The sheets found in a drawing and where each PDF will go."""

    drawing: Path
    results: list[SheetResult]
    skipped: list[Skipped]
    sheets: list[Sheet] = field(repr=False)
    # Sheet numbers that several sheets share, with how many: usually a title block copied without renumbering.
    duplicates: dict[str, int] = field(default_factory=dict)


def plan(cad: CadCraft, drawing: Path, out_dir: Path, options: Options, stem: str | None = None) -> Plan:
    """Find the sheets in `drawing`. PDFs are named "<stem> - <sheet>.pdf" (stem defaults to the file name)."""
    sheets, skipped = find_sheets(rectangles(cad.polylines(drawing)), cad.texts(drawing), options.title_pattern)
    stem = stem or drawing.stem
    results = []
    for sheet, label in zip(sheets, labels(sheets), strict=True):
        layout = sheet.plot(options.unit_mm, options.margins_mm)
        out = out_dir / f"{stem} - {safe_filename(label)}.pdf"
        results.append(SheetResult(sheet.name, sheet.scale, layout.page_mm, sheet.double, out, label=label))
    return Plan(drawing, results, skipped, sheets, duplicates(sheets))


def export(
    cad: CadCraft,
    p: Plan,
    options: Options,
    workers: int = 1,
    on_done: Callable[[SheetResult], None] | None = None,
) -> list[SheetResult]:
    """Export every planned sheet. Failures are recorded on the result instead of stopping the run."""

    def one(pair: tuple[Sheet, SheetResult]) -> SheetResult:
        sheet, result = pair
        layout = sheet.plot(options.unit_mm, options.margins_mm)
        result.file.parent.mkdir(parents=True, exist_ok=True)
        try:
            cad.export_pdf(
                p.drawing,
                result.file,
                layout.window.box,
                options.unit_mm / sheet.scale,
                layout.page_mm,
                layout.hide,
            )
        except CadCraftError as e:
            result.error = str(e)
        if on_done:
            on_done(result)
        return result

    pairs = list(zip(p.sheets, p.results, strict=True))
    if workers <= 1:
        return [one(pair) for pair in pairs]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, pairs))
