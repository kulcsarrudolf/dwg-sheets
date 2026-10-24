"""dwg-sheets: export every sheet drawn in model space to its own PDF."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .cadcraft import CadCraft, CadCraftError
from .export import Options, export, plan
from .raster import PNG_QUALITY
from .sheets import DEFAULT_MARGINS_MM, DEFAULT_TITLE_PATTERN, UNIT_MM


def _margins(value: str) -> tuple[float, float, float, float]:
    try:
        parts = tuple(float(v) for v in value.split(","))
    except ValueError:
        parts = ()
    if len(parts) != 4 or any(v < 0 for v in parts):
        raise argparse.ArgumentTypeError("expected four numbers >= 0: LEFT,BOTTOM,RIGHT,TOP (mm)")
    return parts  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="dwg-sheets",
        description="Export every sheet drawn in model space of a DWG/DXF to its own PDF, at true scale.",
    )
    p.add_argument("drawing", type=Path, help="input .dwg or .dxf file")
    p.add_argument("-o", "--out", type=Path, help='output folder (default: "<drawing name> - PDF" next to the drawing)')
    p.add_argument("--units", choices=sorted(UNIT_MM), default="m", help="drawing units (default: m)")
    p.add_argument(
        "--title-pattern",
        default=DEFAULT_TITLE_PATTERN,
        help="regex that marks a title block; its first group is the sheet name (default matches 'PL. NR. A07')",
    )
    p.add_argument(
        "--margins",
        type=_margins,
        default=DEFAULT_MARGINS_MM,
        metavar="L,B,R,T",
        help="page margins in mm around a single-line frame (default: 20,10,10,10)",
    )
    p.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=min(4, os.cpu_count() or 1),
        help="sheets to export in parallel (default: up to 4)",
    )
    p.add_argument(
        "--png",
        nargs="?",
        const="standard",
        choices=sorted(PNG_QUALITY),
        help="also write a PNG of each sheet: 'standard' (150 dpi, the default) or '2x' (300 dpi, sharper)",
    )
    p.add_argument("--dry-run", action="store_true", help="list the sheets found without exporting")
    p.add_argument("--cadcraft", default="cadcraft-cli", help="path to cadcraft-cli (default: found on PATH)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)

    drawing: Path = args.drawing.expanduser().resolve()
    if not drawing.is_file():
        p.error(f"no such file: {drawing}")
    out_dir: Path = (args.out or drawing.with_name(f"{drawing.stem} - PDF")).expanduser().resolve()
    options = Options(UNIT_MM[args.units], args.margins, args.title_pattern, PNG_QUALITY.get(args.png))

    try:
        cad = CadCraft(args.cadcraft)
        found = plan(cad, drawing, out_dir, options)
    except CadCraftError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    for s in found.skipped:
        print(f"skip {s.name}: {s.reason}", file=sys.stderr)
    if found.duplicates:
        shared = ", ".join(f"{name} ({n} sheets)" for name, n in found.duplicates.items())
        print(
            f"warning: several sheets share a number: {shared}. Their files are numbered -1, -2, ...", file=sys.stderr
        )
    if not found.results:
        print("No sheets found. Check --title-pattern and --units.", file=sys.stderr)
        return 1

    if args.dry_run:
        for r in found.results:
            print(r.describe())
        print(f"{len(found.results)} sheet(s) found")
        return 0

    results = export(cad, found, options, workers=max(1, args.jobs))
    failures = 0
    for r in results:
        if r.ok:
            png = f" + {r.png.name} ({r.png_dpi} dpi)" if r.png else ""
            print(f"{r.describe()} -> {r.file.name}{png}")
        else:
            failures += 1
            print(f"{r.describe()} -> FAILED: {r.error}", file=sys.stderr)
    print(f"{len(results) - failures} sheet(s) exported to {out_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
