import re
import subprocess
import sys
from pathlib import Path

import pytest
from babel.messages.pofile import read_po

from dwg_sheets_to_pdf.web.i18n import LANGUAGES, negotiate, translator

ROOT = Path(__file__).parents[1]
LOCALES = ROOT / "src/dwg_sheets_to_pdf/web/locales"
TRANSLATED = [lang for lang in LANGUAGES if lang != "en"]
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
ROMANIAN_DIACRITICS = re.compile("[ăâîșțşţĂÂÎȘȚŞŢ]")


def catalog(lang):
    path = LOCALES / ("messages.pot" if lang is None else f"{lang}/LC_MESSAGES/messages.po")
    with path.open("rb") as f:
        return read_po(f, locale=lang)


def ids(cat):
    return {m.id if isinstance(m.id, str) else tuple(m.id) for m in cat if m.id}


def test_template_matches_the_code(tmp_path):
    """messages.pot must hold exactly the texts in the code and templates (see docs/translations.md)."""
    out = tmp_path / "messages.pot"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "babel.messages.frontend",
            "-q",
            "extract",
            "-F",
            "babel.cfg",
            "-k",
            "N_",
            "-o",
            str(out),
            ".",
        ],
        cwd=ROOT,
        check=True,
    )
    with out.open("rb") as f:
        fresh = read_po(f)
    assert ids(fresh) == ids(catalog(None)), "Run pybabel extract (docs/translations.md)"


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_text_is_translated(lang):
    template, cat = catalog(None), catalog(lang)
    assert ids(cat) == ids(template), "Run pybabel update (docs/translations.md)"
    for m in cat:
        if not m.id:
            continue
        assert not m.fuzzy, f"{lang}: fuzzy entry {m.id!r}"
        forms = m.string if isinstance(m.string, tuple) else (m.string,)
        assert all(forms), f"{lang}: untranslated {m.id!r}"
        english = m.id if isinstance(m.id, str) else m.id[-1]
        for form in forms:
            assert set(PLACEHOLDER.findall(form)) == set(PLACEHOLDER.findall(english)), (
                f"{lang}: placeholders in {form!r}"
            )


def test_romanian_has_no_diacritics():
    for m in catalog("ro"):
        forms = m.string if isinstance(m.string, tuple) else (m.string,)
        for form in forms:
            assert not ROMANIAN_DIACRITICS.search(form or ""), form
    assert not ROMANIAN_DIACRITICS.search(LANGUAGES["ro"])


def test_plurals_and_numbers():
    sheets = lambda t, n: t.ngettext("%(count)s sheet", "%(count)s sheets", n) % {"count": n}  # noqa: E731
    en, ro, hu = translator("en"), translator("ro"), translator("hu")
    assert [sheets(en, n) for n in (1, 3, 20)] == ["1 sheet", "3 sheets", "20 sheets"]
    assert [sheets(ro, n) for n in (1, 3, 20)] == ["1 plansa", "3 planse", "20 de planse"]
    assert [sheets(hu, n) for n in (1, 3, 20)] == ["1 tervlap", "3 tervlap", "20 tervlap"]
    assert en.number(1633.57) == "1,633.6"
    assert ro.number(1633.57) == "1.633,6"
    assert hu.number(594.0) == "594"
    assert ro.error("partial", {"failed": 1, "total": 12}) == "1 din 12 planse nu au putut fi exportate."
    assert hu.error("too_large", {"mb": 100}) == "A fájl nagyobb, mint 100 MB."
    assert ro.skip_reason("no_frame", "fallback") == "nu are chenar in jurul cartusului"
    assert ro.skip_reason("unknown", "fallback") == "fallback"


@pytest.mark.parametrize(
    ("query", "cookie", "header", "expected"),
    [
        ("ro", "hu", "en", "ro"),  # ?lang= wins
        (None, "hu", "ro-RO", "hu"),  # then the saved choice
        (None, None, "de-DE,hu;q=0.8,ro;q=0.9", "ro"),  # then the browser's languages, by preference
        (None, None, "en-GB,en;q=0.9", "en"),
        ("xx", "yy", "de, fr;q=0.5", "en"),  # unknown everywhere: English
        (None, None, None, "en"),
    ],
)
def test_negotiate(query, cookie, header, expected):
    assert negotiate(query, cookie, header) == expected
