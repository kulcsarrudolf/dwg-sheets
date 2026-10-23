"""Find the sheets drawn in model space and work out how to plot each one.

A sheet is found from its title block: a text such as "PL. NR. A07" names the
sheet, the largest closed rectangle around that text (that holds no other
title block) is the sheet frame, and the "1:N" scale text inside the frame
closest to the title block gives the plot scale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

Point = tuple[float, float]

DEFAULT_TITLE_PATTERN = r"PL\.?\s*NR\.?\s*:?\s*(\S+)"
SCALE_PATTERN = re.compile(r"1\s*:\s*(\d+(?:[.,]\d+)?)")

# Paper millimetres per drawing unit at 1:1.
UNIT_MM = {"m": 1000.0, "cm": 10.0, "mm": 1.0}

_EPS = 1e-6


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.height

    def contains(self, p: Point) -> bool:
        return self.x0 <= p[0] <= self.x1 and self.y0 <= p[1] <= self.y1


@dataclass(frozen=True)
class Sheet:
    name: str
    frame: Rect
    scale: float  # the N in 1:N

    def page_size_mm(self, unit_mm: float) -> tuple[float, float]:
        """Page width and height in mm that hold the frame at true scale."""
        factor = unit_mm / self.scale
        return round(self.frame.width * factor, 2), round(self.frame.height * factor, 2)


@dataclass(frozen=True)
class Skipped:
    name: str
    reason: str


def rectangles(entities: list[dict]) -> list[Rect]:
    """Closed, axis-aligned, straight-sided polylines with four corners."""
    rects = []
    for e in entities:
        g = e.get("geometry") or {}
        verts = g.get("vertices") or []
        if len(verts) not in (4, 5):
            continue
        if any(abs(v.get("bulge", 0.0)) > _EPS for v in verts):
            continue
        pts = [(v["p"]["x"], v["p"]["y"]) for v in verts]
        is_closed = g.get("closed") or _same(pts[0], pts[-1])
        if not is_closed:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        r = Rect(min(xs), min(ys), max(xs), max(ys))
        if r.width <= _EPS or r.height <= _EPS:
            continue
        on_corners = all(
            (abs(x - r.x0) < _EPS or abs(x - r.x1) < _EPS) and (abs(y - r.y0) < _EPS or abs(y - r.y1) < _EPS)
            for x, y in pts
        )
        if on_corners:
            rects.append(r)
    return rects


def find_sheets(
    rects: list[Rect],
    texts: list[dict],
    title_pattern: str = DEFAULT_TITLE_PATTERN,
) -> tuple[list[Sheet], list[Skipped]]:
    """Match title blocks to frames and scales.

    `texts` are items with a `text` string and an `at` [x, y] insertion point.
    """
    title_re = re.compile(title_pattern, re.IGNORECASE | re.DOTALL)
    titles = []
    for t in texts:
        m = title_re.search(t["text"])
        if m:
            titles.append((m.group(1) if m.groups() else m.group(0), _pt(t["at"])))
    scales = []
    for t in texts:
        m = SCALE_PATTERN.search(t["text"])
        if m:
            scales.append((float(m.group(1).replace(",", ".")), _pt(t["at"])))

    sheets: list[Sheet] = []
    skipped: list[Skipped] = []
    for i, (name, at) in enumerate(titles):
        others = [p for j, (_, p) in enumerate(titles) if j != i]
        frames = [r for r in rects if r.contains(at) and not any(r.contains(o) for o in others)]
        if not frames:
            skipped.append(Skipped(name, "no frame around its title block"))
            continue
        frame = max(frames, key=lambda r: r.area)
        inside = [(n, p) for n, p in scales if frame.contains(p)]
        if not inside:
            skipped.append(Skipped(name, "no 1:N scale inside its frame"))
            continue
        scale = min(inside, key=lambda s: _dist2(s[1], at))[0]
        if scale <= 0:
            skipped.append(Skipped(name, f"invalid scale 1:{scale:g}"))
            continue
        sheets.append(Sheet(name, frame, scale))

    sheets.sort(key=lambda s: _natural_key(s.name))
    return sheets, skipped


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("._")
    return cleaned or "sheet"


def _pt(at) -> Point:
    return float(at[0]), float(at[1])


def _same(a: Point, b: Point) -> bool:
    return abs(a[0] - b[0]) < _EPS and abs(a[1] - b[1]) < _EPS


def _dist2(a: Point, b: Point) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _natural_key(s: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", s)]
