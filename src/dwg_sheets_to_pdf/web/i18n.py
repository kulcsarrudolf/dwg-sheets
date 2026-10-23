"""Languages for the web app: gettext catalogs, picking the reader's language, and number formatting.

The catalogs are ordinary gettext `.po` files in `locales/<lang>/LC_MESSAGES/messages.po`, edited by
translators. They are read at start-up (no compile step), so the `.po` file is the only source.
See docs/translations.md.
"""

from __future__ import annotations

import gettext
import io
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from babel import Locale, UnknownLocaleError
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from babel.numbers import format_decimal

# Language code -> name of the language in itself, in the order the switcher shows them.
LANGUAGES = {"en": "English", "ro": "Romana", "hu": "Magyar"}  # Romanian is written without diacritics
DEFAULT_LANGUAGE = "en"
COOKIE = "lang"

LOCALES = files("dwg_sheets_to_pdf.web").joinpath("locales")


def N_(message: str) -> str:
    """Mark a message for extraction without translating it yet (translated when shown)."""
    return message


# Messages behind the stable codes the server uses for errors and skipped sheets.
ERRORS = {
    "bad_type": N_("Choose a .dwg or .dxf file."),
    "too_large": N_("The file is larger than %(mb)s MB."),
    "empty": N_("The file is empty."),
    "bad_images": N_("Choose PDF only, PDF + PNG, or PDF + PNG 2×."),
    "not_found": N_("This export no longer exists. Uploads are deleted after a while, so upload the drawing again."),
    "no_sheets": N_("No sheets found. Each sheet needs a “PL. NR.” title block inside a rectangular frame."),
    "unreadable": N_("The drawing could not be read. Check that it opens in AutoCAD and try again."),
    "unexpected": N_("Something went wrong while exporting. Try again."),
}
SKIP_REASONS = {
    "no_frame": N_("no frame around its title block"),
    "no_scale": N_("no 1:N scale inside its frame"),
    "bad_scale": N_("the scale in its title block is not valid"),
}


@dataclass(frozen=True)
class Translator:
    lang: str
    catalog: gettext.NullTranslations

    def gettext(self, message: str) -> str:
        return self.catalog.gettext(message)

    def ngettext(self, singular: str, plural: str, n: int) -> str:
        return self.catalog.ngettext(singular, plural, n)

    def number(self, value: float) -> str:
        """A number in the reader's format: 1,633.6 (en), 1.633,6 (ro), 1633,6 (hu)."""
        return format_decimal(round(value, 1), format="#,##0.#", locale=self.lang)

    def error(self, code: str | None, params: dict | None = None) -> str:
        if not code:
            return ""
        if code == "partial":
            p = params or {}
            return self.ngettext(
                "%(failed)s of %(total)s sheet could not be exported.",
                "%(failed)s of %(total)s sheets could not be exported.",
                int(p.get("total", 0)),
            ) % {"failed": p.get("failed", 0), "total": p.get("total", 0)}
        message = ERRORS.get(code, ERRORS["unexpected"])
        return self.gettext(message) % (params or {})

    def skip_reason(self, code: str, fallback: str) -> str:
        return self.gettext(SKIP_REASONS[code]) if code in SKIP_REASONS else fallback


@cache
def translator(lang: str) -> Translator:
    if lang not in LANGUAGES:
        lang = DEFAULT_LANGUAGE
    if lang == DEFAULT_LANGUAGE:  # the source language: messages are written in English
        return Translator(lang, gettext.NullTranslations())
    po = LOCALES.joinpath(lang, "LC_MESSAGES", "messages.po")
    with po.open("rb") as f:
        catalog = read_po(f, locale=lang)
    mo = io.BytesIO()
    write_mo(mo, catalog, use_fuzzy=False)
    mo.seek(0)
    return Translator(lang, gettext.GNUTranslations(mo))


def negotiate(query: str | None, cookie: str | None, accept_language: str | None) -> str:
    """The reader's language: ?lang= first, then their saved choice, then the browser's languages."""
    for choice in (query, cookie):
        if choice in LANGUAGES:
            return choice
    for code in _accepted(accept_language or ""):
        try:
            base = Locale.parse(code, sep="-").language
        except (ValueError, UnknownLocaleError):
            continue
        if base in LANGUAGES:
            return base
    return DEFAULT_LANGUAGE


def _accepted(header: str) -> list[str]:
    """Language codes from an Accept-Language header, most preferred first."""
    ranked = []
    for i, part in enumerate(header.split(",")):
        code, _, params = part.strip().partition(";")
        q = 1.0
        if params.strip().startswith("q="):
            try:
                q = float(params.strip()[2:])
            except ValueError:
                q = 0.0
        if code and code != "*" and q > 0:
            ranked.append((-q, i, code))
    return [code for _, _, code in sorted(ranked)]
