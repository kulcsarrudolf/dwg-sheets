# dwg-sheets-to-pdf

Export every sheet of a DWG or DXF drawing to its own PDF, at true scale, with one command.

Many drawings keep all their sheets side by side in model space instead of in paper-space layouts.
Printing them usually means framing each sheet by hand, picking a paper size and a scale, and plotting.
This tool does that for every sheet at once.

It runs on [CADCraft](https://github.com/storytold/cadcraft), a free, open-source AutoCAD-style CAD app, so you don't need AutoCAD.

## How it finds the sheets

For each title block in the drawing:

1. A text such as `PL. NR. A07` marks the title block and gives the sheet name.
2. The largest closed rectangle around that text (one that holds no other title block) is the sheet frame.
3. The `1:N` scale text inside the frame nearest to the title block (e.g. `SCARA 1:200`) is the plot scale.
4. The frame is plotted at that scale on a page exactly its size.
   A frame 270 x 118.8 m at 1:200 becomes a 1350 x 594 mm PDF page.

Sheets without a frame or a scale are skipped and listed, so nothing is silently left out.

## Install

1. Install the CADCraft command-line tool, `cadcraft-cli`, from the [CADCraft releases](https://github.com/storytold/cadcraft/releases) (macOS: `cadcraft-cli-<version>-macos-universal.zip`) and put it on your `PATH`.
2. Install this tool with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install git+https://github.com/kulcsarrudolf/dwg-sheets-to-pdf
```

## Use

```sh
dwg-sheets-to-pdf "Project.dwg"
```

The PDFs go to a `Project - PDF` folder next to the drawing, one file per sheet: `Project - A03.pdf`, `Project - A04.pdf`, and so on.

```text
A03: 1:200, 1603.57 x 574 mm -> Project - A03.pdf
A04: 1:100, 841 x 1188 mm -> Project - A04.pdf
A05: 1:50, 891 x 420 mm -> Project - A05.pdf
...
12 sheet(s) exported to /Users/me/Desktop/Project - PDF
```

Options:

| Option | Meaning |
|---|---|
| `-o, --out DIR` | Output folder |
| `--units m\|cm\|mm` | Drawing units (default `m`) |
| `--title-pattern REGEX` | What marks a title block; the first group is the sheet name. Default matches `PL. NR. A07`. Example: `--title-pattern 'Sheet no:\s*(\S+)'` |
| `--dry-run` | List the sheets and page sizes without exporting |
| `--cadcraft PATH` | Path to `cadcraft-cli` if it is not on `PATH` |

The input file is only read, never changed.

## Limits

- Frames must be closed rectangular polylines. A frame drawn as four separate lines is not found; the next rectangle around the title block is used instead, if there is one.
- Colours are plotted as drawn.
- CADCraft is in early development. Check the PDFs before you send them.

## Develop

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## License

MIT
