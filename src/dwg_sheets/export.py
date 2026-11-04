"""Find the sheets in a drawing and export each one to its own PDF.

Shared by the command line and the web app.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .cadcraft import CadCraft, CadCraftError
from .profile import DEFAULT_UNITS, Profile, infer_units
from .raster import pdf_thumbnail, pdf_to_png
from .sheets import (
    DEFAULT_MARGINS_MM,
    DEFAULT_SCALE_PATTERN,
    DEFAULT_TITLE_PATTERN,
    Rect,
    Sheet,
    Skipped,
    duplicates,
    find_sheets,
    first_match,
    labels,
    rectangles,
    safe_filename,
)

if TYPE_CHECKING:
    from .agent import Agent


@dataclass(frozen=True)
class Options:
    """What the person asked for. Anything left open is worked out per drawing (see `read_profile`)."""

    # None: the AI agent finds the patterns when there is one, otherwise the built-in ones are used.
    title_pattern: str | None = None
    scale_pattern: str | None = None
    units: str = "auto"  # auto (from the frame sizes) | m | cm | mm
    margins_mm: tuple[float, float, float, float] = DEFAULT_MARGINS_MM
    png_dpi: int | None = None  # also write a PNG of each sheet at this resolution
    thumb_box: tuple[int, int] | None = None  # also write a small preview fitted inside this box (pixels)


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
    png: Path | None = None  # where the PNG goes, when images were asked for
    png_dpi: int | None = None  # the resolution it was drawn at (lower than asked for very large sheets)
    thumb: Path | None = None  # where the preview goes, when previews were asked for; None if it failed

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
    # The settings the drawing was read with, and where each came from.
    profile: Profile = field(default_factory=Profile)


def plan(
    cad: CadCraft,
    drawing: Path,
    out_dir: Path,
    options: Options,
    stem: str | None = None,
    agent: Agent | None = None,
) -> Plan:
    """Find the sheets in `drawing`. PDFs are named "<stem> - <sheet>.pdf" (stem defaults to the file name)."""
    rects, texts = rectangles(cad.polylines(drawing)), cad.texts(drawing)
    profile, sheets, skipped = read_profile(rects, texts, options, agent)
    stem = stem or drawing.stem
    results = []
    for sheet, label in zip(sheets, labels(sheets), strict=True):
        layout = sheet.plot(profile.unit_mm, profile.margins_mm)
        out = out_dir / f"{stem} - {safe_filename(label)}.pdf"
        png = out.with_suffix(".png") if options.png_dpi else None
        thumb = out.with_suffix(".preview.webp") if options.thumb_box else None
        results.append(
            SheetResult(sheet.name, sheet.scale, layout.page_mm, sheet.double, out, label=label, png=png, thumb=thumb)
        )
    return Plan(drawing, results, skipped, sheets, duplicates(sheets), profile)


def read_profile(
    rects: list[Rect], texts: list[dict], options: Options, agent: Agent | None = None
) -> tuple[Profile, list[Sheet], list[Skipped]]:
    """Settle every setting for this drawing, then find its sheets with them.

    Patterns the person gave are used as they are. Otherwise the agent, when there is one, looks for
    better ones than the built-in patterns. Units left on auto are the ones that give the sheets real
    paper sizes.
    """
    ai: dict = {}
    if options.title_pattern or options.scale_pattern:
        title = options.title_pattern or DEFAULT_TITLE_PATTERN
        scale = options.scale_pattern or DEFAULT_SCALE_PATTERN
        patterns_from = "user"
    elif agent is not None:
        found = agent.detect(rects, texts)
        title, scale = found.title_pattern, found.scale_pattern
        patterns_from = "ai" if found.status in ("improved", "cached") else "default"
        ai = {"ai_model": found.model, "ai_status": found.status, "ai_cost_usd": found.cost_usd}
    else:
        title, scale, patterns_from = DEFAULT_TITLE_PATTERN, DEFAULT_SCALE_PATTERN, "default"

    sheets, skipped = find_sheets(rects, texts, title, scale)
    if options.units != "auto":
        units, units_from = options.units, "user"
    else:
        inferred = infer_units(sheets, options.margins_mm)
        units, units_from = (inferred, "frames") if inferred else (DEFAULT_UNITS, "default")
    profile = Profile(
        title_pattern=title,
        scale_pattern=scale,
        units=units,
        margins_mm=options.margins_mm,
        patterns_from=patterns_from,
        units_from=units_from,
        example=first_match(texts, title),
        **ai,
    )
    return profile, sheets, skipped


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
        layout = sheet.plot(p.profile.unit_mm, p.profile.margins_mm)
        result.file.parent.mkdir(parents=True, exist_ok=True)
        try:
            cad.export_pdf(
                p.drawing,
                result.file,
                layout.window.box,
                p.profile.unit_mm / sheet.scale,
                layout.page_mm,
                layout.hide,
            )
        except CadCraftError as e:
            result.error = str(e)
        if result.ok and result.png and options.png_dpi:
            try:
                result.png_dpi = pdf_to_png(result.file, result.png, options.png_dpi)
            except Exception as e:  # PDFium reports problems with its own exception types
                result.error = f"PNG: {e}"
        if result.thumb and options.thumb_box:
            try:
                if result.ok:
                    pdf_thumbnail(result.file, result.thumb, options.thumb_box)
                else:
                    result.thumb = None
            except Exception:  # a missing preview is cosmetic: the sheet itself is fine
                result.thumb = None
        if on_done:
            on_done(result)
        return result

    pairs = list(zip(p.sheets, p.results, strict=True))
    if workers <= 1:
        return [one(pair) for pair in pairs]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, pairs))
