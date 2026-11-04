"""The settings a drawing is read with, and where each one came from.

A drawing's profile is what the sheet finder needs to know about how that office draws:
the text that marks a title block, how the scale is written, the drawing units, and the
page margins around a single frame. Each comes from the person (a CLI flag or the web form),
from the AI agent (see agent.py), from the frame sizes (units), or from the built-in defaults.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .sheets import DEFAULT_MARGINS_MM, DEFAULT_SCALE_PATTERN, DEFAULT_TITLE_PATTERN, UNIT_MM, Sheet, compile_pattern

UNITS = tuple(UNIT_MM)  # m, cm, mm
DEFAULT_UNITS = "m"

# A plotted page counts as a real paper size when its shorter side is in this range (mm): from A5
# (148) to a little over A0 (841) and the widest plotter rolls (1067, 1189). The units differ by 10×,
# so for a given frame usually only one of them lands in the range.
_PAPER_SHORT_MM = (140.0, 1300.0)
_PAPER_LONG_MAX_MM = 10_000.0

MAX_PATTERN_LENGTH = 300


class ProfileError(ValueError):
    """A setting that cannot be used, with a stable code for translated messages."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Profile:
    """What a drawing was read with. Every value is concrete; the *_from fields say where it came from."""

    title_pattern: str = DEFAULT_TITLE_PATTERN
    scale_pattern: str = DEFAULT_SCALE_PATTERN
    units: str = DEFAULT_UNITS
    margins_mm: tuple[float, float, float, float] = DEFAULT_MARGINS_MM
    patterns_from: str = "default"  # default | ai | user
    units_from: str = "default"  # default | frames | user
    example: str | None = None  # a title text the title pattern matched, to show the reader
    # The AI agent's part, when it ran: the model, what came of it, and what it cost.
    ai_model: str | None = None
    ai_status: str | None = None  # improved | agreed | failed | cached
    ai_cost_usd: float | None = None

    @property
    def unit_mm(self) -> float:
        return UNIT_MM[self.units]

    def to_json(self) -> dict:
        data = asdict(self)
        data["margins_mm"] = list(self.margins_mm)
        return data

    @classmethod
    def from_json(cls, data: dict) -> Profile:
        return cls(**{**data, "margins_mm": tuple(data["margins_mm"])})


def check_pattern(pattern: str, what: str = "title") -> str:
    """A pattern the person or the model gave, checked before it is used."""
    pattern = pattern.strip()
    if not pattern:
        raise ProfileError("bad_pattern", f"The {what} pattern is empty.")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ProfileError("bad_pattern", f"The {what} pattern is longer than {MAX_PATTERN_LENGTH} characters.")
    try:
        compiled = compile_pattern(pattern)
    except re.error as e:
        raise ProfileError("bad_pattern", f"The {what} pattern is not a valid regular expression: {e}.") from None
    if compiled.groups < 1:
        raise ProfileError("bad_pattern", f"The {what} pattern needs a group in brackets (...) around the value.")
    return pattern


def check_units(units: str, allow_auto: bool = True) -> str:
    if units in UNITS or (allow_auto and units == "auto"):
        return units
    raise ProfileError("bad_units", f"Units must be {', '.join(('auto', *UNITS) if allow_auto else UNITS)}.")


def check_margins(margins: tuple[float, ...] | list[float]) -> tuple[float, float, float, float]:
    values = tuple(float(m) for m in margins)
    if len(values) != 4 or any(not (0 <= m <= 500) for m in values):
        raise ProfileError("bad_margins", "Margins must be four numbers from 0 to 500 mm: left, bottom, right, top.")
    return values  # type: ignore[return-value]


def infer_units(sheets: list[Sheet], margins_mm: tuple[float, float, float, float]) -> str | None:
    """The drawing units that give the found sheets real paper sizes, or None if no unit does.

    A 270 x 118.8 frame at 1:200 is a 1350 x 594 mm page in metres, but 135 x 59 mm in
    centimetres and 13.5 x 5.9 mm in millimetres: only metres is a paper size.
    """
    if not sheets:
        return None
    scores = {}
    for units in UNITS:
        scores[units] = sum(_is_paper(s.plot(UNIT_MM[units], margins_mm).page_mm) for s in sheets)
    best = max(scores.values())
    if best == 0:
        return None
    # On a tie, keep the default: it is what the tool always used.
    winners = [u for u in UNITS if scores[u] == best]
    return DEFAULT_UNITS if DEFAULT_UNITS in winners else winners[0]


def _is_paper(page_mm: tuple[float, float]) -> bool:
    short, long = sorted(page_mm)
    return _PAPER_SHORT_MM[0] <= short <= _PAPER_SHORT_MM[1] and long <= _PAPER_LONG_MAX_MM
