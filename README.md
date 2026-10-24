# dwg-sheets

Tools for the sheets of a DWG or DXF drawing.
Today it exports every sheet to its own PDF, at true scale, with one command or from a web page.

Many drawings keep all their sheets side by side in model space instead of in paper-space layouts.
Printing them usually means framing each sheet by hand, picking a paper size and a scale, and plotting.
This tool does that for every sheet at once.

It runs on [CADCraft](https://github.com/storytold/cadcraft), a free, open-source AutoCAD-style CAD app, so you don't need AutoCAD.

## How it finds the sheets

For each title block in the drawing:

1. A text such as `PL. NR. A07` marks the title block and gives the sheet name.
2. The largest closed rectangle around that text (one that holds no other title block) is the sheet frame.
3. The `1:N` scale text inside the frame nearest to the title block (e.g. `SCARA 1:200`) is the plot scale.
4. The sheet is plotted at that scale, edge to edge, on a page sized to fit:
   - **Double frame** (an outer line with the drawn border just inside it): the outer line is the page edge and is not printed.
     A frame 270 x 118.8 m at 1:200 becomes a 1350 x 594 mm page.
   - **Single frame** (one border line): the page is the border plus margins, 20 mm on the left for binding and 10 mm on the other sides (change with `--margins`).
     A frame 63 x 29.7 m at 1:100 becomes a 660 x 317 mm page.

Sheets without a frame or a scale are skipped and listed, so nothing is silently left out.

## Web app (Docker)

Upload a drawing in the browser, watch its sheets plot, and download them one by one or as a ZIP.
The sheets show as a grid of previews (four across on a wide screen, one per row on a phone).
Click a sheet to open its PDF.
Tick a few (shift-click ticks a range) to download just those as one ZIP; scripts can ask for the same with `/api/jobs/<id>/zip?sheet=0&sheet=3`, counting sheets from 0 in the job's list.
The page is in English, Romanian and Hungarian: it follows the browser's language, remembers the reader's choice, and takes `?lang=en|ro|hu` in links.
Translations are gettext `.po` files; [docs/translations.md](docs/translations.md) explains how to edit them or add a language.

The pages are rendered on the server with Jinja2 and updated in place with [htmx](https://htmx.org/) (pinned, served by the app with the fonts, so nothing loads from other sites).
Each export has its own address (`/jobs/<id>`), so a reload or a shared link shows the same result while it lives.

Next to the PDFs the page can also make PNG images, for viewers and tools that don't handle vector PDFs well: **PDF + PNG** at 150 dpi, or **PDF + PNG 2×** at 300 dpi.
The PDFs themselves are vector and sharp at any zoom; the images are drawn from them with PDFium, so they match exactly.
Very large sheets are drawn at a lower resolution so one image stays under 200 megapixels.

```sh
docker compose up -d --build
```

Then open <http://localhost:8000>.

The image is self-contained and runs on `linux/amd64` and `linux/arm64`, so it can go to any container service (Cloud Run, Azure Container Apps, Fly.io, ECS, Kubernetes) unchanged:

- CADCraft's command-line tool comes from its official Linux release, pinned to a version and checked against its SHA-256.
- Liberation fonts are installed under the Arial, Times New Roman and Courier New names that AutoCAD drawings ask for. They have the same letter widths, so title blocks lay out as designed.
- It runs as a non-root user, listens on `$PORT`, has a `/healthz` endpoint, and keeps uploads only in temporary storage.

Settings, all optional:

| Variable | Default | Meaning |
|---|---|---|
| `APP_PASSWORD` | none | Require this password (HTTP Basic, any user name). Set it before exposing the app beyond your own machine. |
| `PORT` | `8000` | Port to listen on |
| `MAX_UPLOAD_MB` | `100` | Largest drawing accepted |
| `JOB_TTL_MINUTES` | `30` | Uploads and PDFs are deleted after this long |
| `MAX_CONCURRENT_JOBS` | `2` | Drawings processed at the same time |
| `EXPORT_WORKERS` | `4` | Sheets plotted in parallel per drawing |
| `WORK_DIR` | `/tmp/jobs` | Where jobs are kept while they live |

Job state lives on the local disk of the container, so run a single instance (or pin each user to one instance).

## Install the command-line tool

1. Install the CADCraft command-line tool, `cadcraft-cli`, from the [CADCraft releases](https://github.com/storytold/cadcraft/releases) (macOS: `cadcraft-cli-<version>-macos-universal.zip`) and put it on your `PATH`.
2. Install this tool with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install git+https://github.com/kulcsarrudolf/dwg-sheets
```

## Use

```sh
dwg-sheets "Project.dwg"
```

The PDFs go to a `Project - PDF` folder next to the drawing, one file per sheet: `Project - A03.pdf`, `Project - A04.pdf`, and so on.

```text
A03: 1:200, 1633.57 x 594 mm (single frame, margins added) -> Project - A03.pdf
A04: 1:100, 841 x 1188 mm (double frame, outer line hidden) -> Project - A04.pdf
A05: 1:50, 891 x 420 mm (double frame, outer line hidden) -> Project - A05.pdf
...
12 sheet(s) exported to /Users/me/Desktop/Project - PDF
```

Options:

| Option | Meaning |
|---|---|
| `-o, --out DIR` | Output folder |
| `--units m\|cm\|mm` | Drawing units (default `m`) |
| `--title-pattern REGEX` | What marks a title block; the first group is the sheet name. Default matches `PL. NR. A07`. Example: `--title-pattern 'Sheet no:\s*(\S+)'` |
| `--margins L,B,R,T` | Page margins in mm around a single frame (default `20,10,10,10`) |
| `--png [standard\|2x]` | Also write a PNG image of each sheet: `standard` is 150 dpi, `2x` is 300 dpi |
| `--dry-run` | List the sheets and page sizes without exporting |
| `--cadcraft PATH` | Path to `cadcraft-cli` if it is not on `PATH` |

The input file is only read, never changed.
The outer frame line is left out only inside the export run; the drawing is not saved.

## Limits

- Frames must be closed rectangular polylines. A frame drawn as four separate lines is not found; the next rectangle around the title block is used instead, if there is one.
- Colours are plotted as drawn.
- CADCraft is in early development. Check the PDFs before you send them.

## Develop

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run dwg-sheets-web    # the web app without Docker, on http://localhost:8000
```

## License

MIT
