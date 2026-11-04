from dwg_sheets.cli import describe_profile
from dwg_sheets.profile import Profile


def test_profile_line_says_where_each_setting_came_from():
    line = describe_profile(
        Profile(
            title_pattern=r"Sheet no:\s*(\S+)",
            units="mm",
            patterns_from="ai",
            units_from="frames",
            example="Sheet no:\n S-01",
            ai_model="x/model",
            ai_status="improved",
            ai_cost_usd=0.00213,
        )
    )
    assert line == (
        r'title pattern Sheet no:\s*(\S+) (found by x/model), e.g. "Sheet no: S-01"; '
        "units mm (from the frame sizes); AI cost $0.0021"
    )
    assert "AI detection failed" in describe_profile(Profile(ai_status="failed", ai_model="x"))
