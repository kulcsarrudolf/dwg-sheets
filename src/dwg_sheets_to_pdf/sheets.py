"""Find the sheets drawn in model space and work out how to plot each one.

A sheet is found from its title block: a text such as "PL. NR. A07" names the
sheet, the largest closed rectangle around that text (that holds no other
title block) is the sheet frame, and the "1:N" scale text inside the frame
closest to the title block gives the plot scale.

A frame is either single (one border line) or double (an outer trimming line
with the drawn border just inside it). A double frame is the page: its outer
line marks where the paper is cut and is not printed. A single frame is the
drawn border; the page is that border plus the margins (by default 20 mm on
the left for binding and 10 mm elsewhere, the same as the double frames).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

Point = tuple[float, float]

DEFAULT_TITLE_PATTERN = r"PL\.?\s*NR\.?\s*:?\s*(\S+)"
SCALE_PATTERN = re.compile(r"1\s*:\s*(\d+(?:[.,]\d+)?)")

# Paper millimetres per drawing unit at 1:1.
UNIT_MM = {"m": 1000.0, "cm": 10.0, "mm": 1.0}

# Page margins (left, bottom, right, top) in paper mm around a single frame.
DEFAULT_MARGINS_MM = (20.0, 10.0, 10.0, 10.0)

# An inner border counts as the second line of a double frame when every gap to
# the outer line is at most this share of the frame's shorter side.
_MAX_BORDER_GAP = 0.1

_EPS = 1e-6


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float
    handle: str = field(default="", compare=False)

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

    def same_box(self, other: Rect) -> bool:
        return all(abs(a - b) < _EPS for a, b in zip(self.box, other.box, strict=True))

    def encloses(self, other: Rect) -> bool:
        return (
            self.x0 - _EPS <= other.x0
            and self.y0 - _EPS <= other.y0
            and other.x1 <= self.x1 + _EPS
            and other.y1 <= self.y1 + _EPS
        )

    def grow(self, left: float, bottom: float, right: float, top: float) -> Rect:
        return Rect(self.x0 - left, self.y0 - bottom, self.x1 + right, self.y1 + top)

    @property
    def box(self) -> tuple[float, float, float, float]:
        return self.x0, self.y0, self.x1, self.y1


@dataclass(frozen=True)
class Plot:
    """What to plot for one sheet: the model-space window, the page, and lines to leave out."""

    window: Rect
    page_mm: tuple[float, float]
    hide: tuple[str, ...]


@dataclass(frozen=True)
class Sheet:
    name: str
    frame: Rect
    scale: float  # the N in 1:N
    # A double frame: `frame` is the outer trimming line, with the drawn border just inside it.
    double: bool = False
    # Handles of every polyline drawing that outer line, left out of the plot.
    outer_handles: tuple[str, ...] = ()

    def plot(self, unit_mm: float, margins_mm: tuple[float, float, float, float] = DEFAULT_MARGINS_MM) -> Plot:
        """The page at true scale. A double frame is the page; a single frame gets margins around it."""
        mm_per_unit = unit_mm / self.scale
        if self.double:
            window = self.frame
        else:
            window = self.frame.grow(*(m / mm_per_unit for m in margins_mm))
        page = (round(window.width * mm_per_unit, 2), round(window.height * mm_per_unit, 2))
        return Plot(window, page, self.outer_handles)


@dataclass(frozen=True)
class Skipped:
    name: str
    reason: str
    code: str = ""  # stable id for the reason (no_frame, no_scale, bad_scale), for translated messages


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
        r = Rect(min(xs), min(ys), max(xs), max(ys), e.get("handle", ""))
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
            skipped.append(Skipped(name, "no frame around its title block", "no_frame"))
            continue
        frame = max(frames, key=lambda r: r.area)
        inside = [(n, p) for n, p in scales if frame.contains(p)]
        if not inside:
            skipped.append(Skipped(name, "no 1:N scale inside its frame", "no_scale"))
            continue
        scale = min(inside, key=lambda s: _dist2(s[1], at))[0]
        if scale <= 0:
            skipped.append(Skipped(name, f"invalid scale 1:{scale:g}", "bad_scale"))
            continue
        double = _inner_border(frame, rects) is not None
        outer_handles = tuple(r.handle for r in rects if double and r.same_box(frame) and r.handle)
        sheets.append(Sheet(name, frame, scale, double, outer_handles))

    sheets.sort(key=lambda s: _natural_key(s.name))
    return sheets, skipped


def _inner_border(frame: Rect, rects: list[Rect]) -> Rect | None:
    """The drawn border just inside `frame`, if `frame` is the outer line of a double frame."""
    limit = _MAX_BORDER_GAP * min(frame.width, frame.height)
    best = None
    for r in rects:
        if r.same_box(frame) or not frame.encloses(r):
            continue
        gaps = (r.x0 - frame.x0, r.y0 - frame.y0, frame.x1 - r.x1, frame.y1 - r.y1)
        if all(_EPS < g <= limit for g in gaps) and (best is None or r.area > best.area):
            best = r
    return best


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
