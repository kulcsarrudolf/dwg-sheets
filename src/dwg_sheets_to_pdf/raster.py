"""Images of the exported PDFs: full PNGs for viewers that don't handle vector PDFs well, and small previews.

The PDF is rendered with PDFium (the engine in Chrome), so the image matches the PDF exactly.
"""

from __future__ import annotations

import math
import threading
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageFilter

# Image quality: dots per inch on the printed sheet.
PNG_QUALITY = {"standard": 150, "2x": 300}

# A 1634 x 594 mm sheet at 300 dpi is about 135 megapixels. Larger pages are drawn at a lower
# resolution so one image can't exhaust memory or become too big to open.
MAX_PIXELS = 200_000_000

# Previews fit this box in pixels: sharp on a high-density screen at the size the web page shows them.
THUMB_BOX = (720, 540)

# Drawing a large page takes a few hundred MB, so draw one at a time even when sheets plot in parallel.
_one_at_a_time = threading.Lock()


def pdf_to_png(pdf: Path, png: Path, dpi: int, max_pixels: int = MAX_PIXELS) -> int:
    """Render the first page of `pdf` to `png` on a white background. Returns the resolution used."""
    with _one_at_a_time:
        doc = pdfium.PdfDocument(str(pdf))
        try:
            page = doc[0]
            width_pt, height_pt = page.get_size()
            scale = dpi / 72
            if width_pt * height_pt * scale * scale > max_pixels:
                # A hair under the limit: PDFium rounds the image size up to whole pixels.
                scale = math.sqrt(max_pixels / (width_pt * height_pt)) * 0.999
            used = round(scale * 72)
            bitmap = page.render(scale=scale, fill_color=(255, 255, 255, 255))
            image = bitmap.to_pil().convert("RGB")
            tmp = png.with_suffix(".png.tmp")
            image.save(tmp, format="PNG", dpi=(used, used))
            tmp.replace(png)
            return used
        finally:
            doc.close()


def pdf_thumbnail(pdf: Path, out: Path, box: tuple[int, int] = THUMB_BOX) -> tuple[int, int]:
    """A small WebP preview of the first page of `pdf`, fitted inside `box`. Returns its size in pixels.

    Drawing lines are a fraction of a pixel wide at this size and would fade to grey. So the page is drawn
    at three times the size with solid (not anti-aliased) lines, each line is thickened to three pixels there,
    and the result is scaled down: every line ends up about one pixel wide, in its full colour.
    """
    with _one_at_a_time:
        doc = pdfium.PdfDocument(str(pdf))
        try:
            page = doc[0]
            width_pt, height_pt = page.get_size()
            scale = min(box[0] / width_pt, box[1] / height_pt)
            size = (max(1, round(width_pt * scale)), max(1, round(height_pt * scale)))
            bitmap = page.render(scale=scale * 3, fill_color=(255, 255, 255, 255), no_smoothpath=True)
            big = bitmap.to_pil().convert("RGB")
        finally:
            doc.close()
    image = big.filter(ImageFilter.MinFilter(3)).resize(size, Image.Resampling.LANCZOS)
    tmp = out.with_name(out.name + ".tmp")
    image.save(tmp, format="WEBP", quality=82, method=4)
    tmp.replace(out)
    return size
