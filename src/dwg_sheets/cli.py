"""dwg-sheets: export every sheet drawn in model space to its own PDF."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import __version__
from .agent import DEFAULT_MODEL, Agent, OpenRouterChat, ProfileCache
from .cadcraft import CadCraft, CadCraftError
from .export import Options, export, plan
from .profile import UNITS, Profile, ProfileError, check_pattern
from .raster import PNG_QUALITY
from .sheets import DEFAULT_MARGINS_MM


def _margins(value: str) -> tuple[float, float, float, float]:
    try:
        parts = tuple(float(v) for v in value.split(","))
    except ValueError:
        parts = ()
    if len(parts) != 4 or any(v < 0 for v in parts):
        raise argparse.ArgumentTypeError("expected four numbers >= 0: LEFT,BOTTOM,RIGHT,TOP (mm)")
    return parts  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.cwd() / ".env")  # settings such as OPENROUTER_API_KEY; the real environment wins
    p = argparse.ArgumentParser(
        prog="dwg-sheets",
        description="Export every sheet drawn in model space of a DWG/DXF to its own PDF, at true scale.",
    )
    p.add_argument("drawing", type=Path, help="input .dwg or .dxf file")
    p.add_argument("-o", "--out", type=Path, help='output folder (default: "<drawing name> - PDF" next to the drawing)')
    p.add_argument(
        "--units",
        choices=("auto", *UNITS),
        default="auto",
        help="drawing units (default: auto, the units that give the sheets real paper sizes)",
    )
    p.add_argument(
        "--title-pattern",
        help="regex that marks a title block; its first group is the sheet name (default matches 'PL. NR. A07')",
    )
    p.add_argument("--scale-pattern", help="regex for the scale; its first group is N in 1:N (default matches '1:100')")
    p.add_argument(
        "--ai",
        action="store_true",
        help="let an AI model find the title and scale patterns (needs OPENROUTER_API_KEY; a few cents per drawing)",
    )
    p.add_argument(
        "--model",
        default=os.environ.get("OPENROUTER_MODEL") or DEFAULT_MODEL,
        help=f"OpenRouter model for --ai (default: $OPENROUTER_MODEL or {DEFAULT_MODEL})",
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
    try:
        title = check_pattern(args.title_pattern, "title") if args.title_pattern else None
        scale = check_pattern(args.scale_pattern, "scale") if args.scale_pattern else None
    except ProfileError as e:
        p.error(str(e))
    agent = None
    if args.ai:
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            p.error("--ai needs an OpenRouter API key in OPENROUTER_API_KEY")
        agent = Agent(OpenRouterChat(key), args.model, ProfileCache(_cache_dir() / "profiles"))
    options = Options(title, scale, args.units, args.margins, PNG_QUALITY.get(args.png))

    try:
        cad = CadCraft(args.cadcraft)
        found = plan(cad, drawing, out_dir, options, agent=agent)
    except CadCraftError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(describe_profile(found.profile), file=sys.stderr)
    for s in found.skipped:
        print(f"skip {s.name}: {s.reason}", file=sys.stderr)
    if found.duplicates:
        shared = ", ".join(f"{name} ({n} sheets)" for name, n in found.duplicates.items())
        print(
            f"warning: several sheets share a number: {shared}. Their files are numbered -1, -2, ...", file=sys.stderr
        )
    if not found.results:
        hint = "Check --title-pattern" + ("" if args.ai else ", or try --ai")
        print(f"No sheets found. {hint}.", file=sys.stderr)
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


def describe_profile(profile: Profile) -> str:
    """One line saying what the drawing was read with, and where each setting came from."""
    source = {"default": "built-in", "user": "given", "ai": f"found by {profile.ai_model}"}[profile.patterns_from]
    line = f"title pattern {profile.title_pattern} ({source})"
    if profile.example:
        line += f', e.g. "{" ".join(profile.example.split())}"'
    units_from = {"frames": "from the frame sizes", "user": "given", "default": "default"}[profile.units_from]
    line += f"; units {profile.units} ({units_from})"
    if profile.ai_status == "failed":
        line += "; AI detection failed, built-in patterns used"
    elif profile.ai_status == "agreed":
        line += "; AI found nothing better"
    if profile.ai_cost_usd:
        line += f"; AI cost ${profile.ai_cost_usd:.4f}"
    return line


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "dwg-sheets"


if __name__ == "__main__":
    sys.exit(main())
