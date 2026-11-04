"""Per-drawing settings: units from frame sizes, and where each setting comes from."""

import pytest

from dwg_sheets.agent import Detection
from dwg_sheets.export import Options, read_profile
from dwg_sheets.profile import Profile, ProfileError, check_margins, check_pattern, check_units, infer_units
from dwg_sheets.sheets import DEFAULT_SCALE_PATTERN, DEFAULT_TITLE_PATTERN, Rect, Sheet


def text(s, x, y):
    return {"text": s, "at": [x, y]}


def sheet(width, height, scale, double=True):
    return Sheet("A1", Rect(0, 0, width, height), scale, double=double)


@pytest.mark.parametrize(
    ("width", "height", "scale", "units"),
    [
        (270, 118.8, 200, "m"),  # 1350 x 594 mm
        (84.1, 59.4, 100, "m"),  # A1 at 1:100 in metres
        (84100, 59400, 100, "mm"),  # the same sheet drawn in millimetres
        (8410, 5940, 100, "cm"),  # and in centimetres
        (841, 594, 1, "mm"),  # a detail at 1:1
    ],
)
def test_units_are_the_ones_that_give_real_paper(width, height, scale, units):
    assert infer_units([sheet(width, height, scale)], (20, 10, 10, 10)) == units


def test_units_unknown_without_sheets_or_paper():
    assert infer_units([], (20, 10, 10, 10)) is None
    assert infer_units([sheet(0.01, 0.01, 1)], (0, 0, 0, 0)) is None  # 10 mm at most: not a page


def test_units_follow_most_sheets():
    sheets = [sheet(84.1, 59.4, 100), sheet(84.1, 59.4, 100), sheet(84.1, 59.4, 10)]  # the odd one is 8.4 m wide
    assert infer_units(sheets, (0, 0, 0, 0)) == "m"


def test_checks():
    assert check_pattern(r"  Sheet (\S+) ") == r"Sheet (\S+)"
    for bad in ("", "Sheet", "Sheet (", "(" + "x" * 400 + ")"):
        with pytest.raises(ProfileError) as e:
            check_pattern(bad)
        assert e.value.code == "bad_pattern"
    assert check_units("auto") == "auto"
    with pytest.raises(ProfileError):
        check_units("ft")
    assert check_margins([20, 10, 10, 10]) == (20.0, 10.0, 10.0, 10.0)
    for bad in ([1, 2, 3], [-1, 0, 0, 0], [0, 0, 0, 900]):
        with pytest.raises(ProfileError):
            check_margins(bad)


def test_profile_round_trips_through_json():
    p = Profile(units="mm", margins_mm=(1, 2, 3, 4), patterns_from="ai", ai_model="x/y", ai_cost_usd=0.001)
    assert Profile.from_json(p.to_json()) == p


RECTS = [Rect(0, 0, 84100, 59400)]  # an A1 frame in millimetres at 1:100
TEXTS = [text("Sheet no: S1", 80000, 1000), text("Scale 1:100", 80000, 500)]


class FakeAgent:
    def __init__(self, status="improved"):
        self.status = status
        self.calls = 0

    def detect(self, rects, texts):
        self.calls += 1
        if self.status == "improved":
            return Detection(r"Sheet no:\s*(\S+)", DEFAULT_SCALE_PATTERN, "improved", "x/model", 0.002)
        return Detection(DEFAULT_TITLE_PATTERN, DEFAULT_SCALE_PATTERN, self.status, "x/model")


def test_profile_from_the_agent_and_the_frames():
    agent = FakeAgent()
    profile, sheets, skipped = read_profile(RECTS, TEXTS, Options(), agent)
    assert [s.name for s in sheets] == ["S1"] and not skipped
    assert (profile.patterns_from, profile.ai_model, profile.ai_status, profile.ai_cost_usd) == (
        "ai",
        "x/model",
        "improved",
        0.002,
    )
    assert (profile.units, profile.units_from) == ("mm", "frames")
    assert profile.example == "Sheet no: S1"


def test_given_settings_skip_the_agent():
    agent = FakeAgent()
    options = Options(title_pattern=r"Sheet no:\s*(\S+)", units="m")
    profile, sheets, _ = read_profile(RECTS, TEXTS, options, agent)
    assert agent.calls == 0
    assert (profile.patterns_from, profile.units_from, profile.units) == ("user", "user", "m")
    assert profile.ai_status is None and len(sheets) == 1


def test_without_an_agent_the_builtin_patterns_are_used():
    profile, sheets, _ = read_profile(RECTS, TEXTS, Options())
    assert (profile.title_pattern, profile.patterns_from) == (DEFAULT_TITLE_PATTERN, "default")
    assert sheets == []
    assert (profile.units, profile.units_from) == ("m", "default")  # nothing to measure


def test_a_failed_agent_is_recorded():
    profile, _, _ = read_profile(RECTS, TEXTS, Options(), FakeAgent("failed"))
    assert (profile.patterns_from, profile.ai_status) == ("default", "failed")
