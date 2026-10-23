"""dwg-sheets-to-pdf: export every sheet drawn in model space to its own PDF."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .cadcraft import CadCraft, CadCraftError
from .sheets import DEFAULT_MARGINS_MM, DEFAULT_TITLE_PATTERN, UNIT_MM, find_sheets, rectangles, safe_filename


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
        prog="dwg-sheets-to-pdf",
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
    p.add_argument("--dry-run", action="store_true", help="list the sheets found without exporting")
    p.add_argument("--cadcraft", default="cadcraft-cli", help="path to cadcraft-cli (default: found on PATH)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)

    drawing: Path = args.drawing.expanduser().resolve()
    if not drawing.is_file():
        p.error(f"no such file: {drawing}")
    out_dir: Path = (args.out or drawing.with_name(f"{drawing.stem} - PDF")).expanduser().resolve()
    unit_mm = UNIT_MM[args.units]

    try:
        cad = CadCraft(args.cadcraft)
        sheets, skipped = find_sheets(rectangles(cad.polylines(drawing)), cad.texts(drawing), args.title_pattern)
    except CadCraftError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    for s in skipped:
        print(f"skip {s.name}: {s.reason}", file=sys.stderr)
    if not sheets:
        print("No sheets found. Check --title-pattern and --units.", file=sys.stderr)
        return 1

    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for sheet in sheets:
        plot = sheet.plot(unit_mm, args.margins)
        w, h = plot.page_mm
        out = out_dir / f"{drawing.stem} - {safe_filename(sheet.name)}.pdf"
        kind = "double frame, outer line hidden" if sheet.double else "single frame, margins added"
        line = f"{sheet.name}: 1:{sheet.scale:g}, {w:g} x {h:g} mm ({kind})"
        if args.dry_run:
            print(line)
            continue
        try:
            cad.export_pdf(drawing, out, plot.window.box, unit_mm / sheet.scale, plot.page_mm, plot.hide)
        except CadCraftError as e:
            failures += 1
            print(f"{line} -> FAILED: {e}", file=sys.stderr)
            continue
        print(f"{line} -> {out.name}")

    done = len(sheets) - failures
    verb = "found" if args.dry_run else f"exported to {out_dir}"
    print(f"{done} sheet(s) {verb}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
