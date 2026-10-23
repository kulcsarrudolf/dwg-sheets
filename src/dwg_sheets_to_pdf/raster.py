"""PNG images of the exported PDFs, for viewers and tools that don't handle vector PDFs well.

The PDF is rendered with PDFium (the engine in Chrome), so the image matches the PDF exactly.
"""

from __future__ import annotations

import math
import threading
from pathlib import Path

import pypdfium2 as pdfium

# Image quality: dots per inch on the printed sheet.
PNG_QUALITY = {"standard": 150, "2x": 300}

# A 1634 x 594 mm sheet at 300 dpi is about 135 megapixels. Larger pages are drawn at a lower
# resolution so one image can't exhaust memory or become too big to open.
MAX_PIXELS = 200_000_000

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
