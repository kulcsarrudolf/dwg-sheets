"""Make the Liberation fonts answer to the Windows font names drawings ask for.

AutoCAD drawings name fonts the Windows way: a text style points at `arial.ttf`
or `times.ttf`, and MTEXT switches fonts by family name (`\\fTimes New Roman|...;`).
CADCraft finds fonts by file name or family name in the font folders, without
fontconfig's substitutions, so on Linux that text falls back to its stroke font
and comes out wider than designed.

Liberation Sans, Serif and Mono have the same metrics as Arial, Times New Roman
and Courier New. This writes copies of them under the Windows file names, with
the family name changed to match. The Liberation fonts are under the SIL Open
Font License, which allows modified copies under a name other than "Liberation".

Usage: python alias_fonts.py SOURCE_DIR OUT_DIR
"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont

# (source file, alias file, alias family, style)
ALIASES = [
    ("LiberationSans-Regular.ttf", "arial.ttf", "Arial", "Regular"),
    ("LiberationSans-Bold.ttf", "arialbd.ttf", "Arial", "Bold"),
    ("LiberationSans-Italic.ttf", "ariali.ttf", "Arial", "Italic"),
    ("LiberationSans-BoldItalic.ttf", "arialbi.ttf", "Arial", "Bold Italic"),
    ("LiberationSerif-Regular.ttf", "times.ttf", "Times New Roman", "Regular"),
    ("LiberationSerif-Bold.ttf", "timesbd.ttf", "Times New Roman", "Bold"),
    ("LiberationSerif-Italic.ttf", "timesi.ttf", "Times New Roman", "Italic"),
    ("LiberationSerif-BoldItalic.ttf", "timesbi.ttf", "Times New Roman", "Bold Italic"),
    ("LiberationMono-Regular.ttf", "cour.ttf", "Courier New", "Regular"),
    ("LiberationMono-Bold.ttf", "courbd.ttf", "Courier New", "Bold"),
    ("LiberationMono-Italic.ttf", "couri.ttf", "Courier New", "Italic"),
    ("LiberationMono-BoldItalic.ttf", "courbi.ttf", "Courier New", "Bold Italic"),
]

NOTE = "Liberation font renamed for drawing compatibility (SIL Open Font License 1.1)."


def alias(src: Path, dest: Path, family: str, style: str) -> None:
    font = TTFont(src)
    name = font["name"]
    full = family if style == "Regular" else f"{family} {style}"
    postscript = f"{family.replace(' ', '')}-{style.replace(' ', '')}-Liberation"
    for record in list(name.names):
        if record.nameID in (16, 17, 21, 22):  # typographic family/style names would override the family
            name.removeNames(nameID=record.nameID)
    for platform, encoding, lang in ((3, 1, 0x409), (1, 0, 0)):
        name.setName(family, 1, platform, encoding, lang)
        name.setName(style, 2, platform, encoding, lang)
        name.setName(f"{full}; Liberation alias", 3, platform, encoding, lang)
        name.setName(full, 4, platform, encoding, lang)
        name.setName(postscript, 6, platform, encoding, lang)
        name.setName(NOTE, 10, platform, encoding, lang)
    font.save(dest)


def main(src_dir: str, out_dir: str) -> None:
    src, out = Path(src_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for source, file, family, style in ALIASES:
        alias(src / source, out / file, family, style)
        print(f"{file}: {family} {style} <- {source}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
