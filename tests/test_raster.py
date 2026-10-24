from PIL import Image

from dwg_sheets.raster import PNG_QUALITY, pdf_thumbnail, pdf_to_png


def make_pdf(path, width_mm, height_mm):
    """A one-page PDF with a black bar, drawn with Pillow (no CADCraft needed)."""
    px = (round(width_mm / 25.4 * 72), round(height_mm / 25.4 * 72))
    image = Image.new("RGB", px, "white")
    image.paste((0, 0, 0), (10, 10, px[0] - 10, 20))
    image.save(path, "PDF", resolution=72)


def test_png_at_the_asked_resolution(tmp_path):
    pdf, png = tmp_path / "a.pdf", tmp_path / "a.png"
    make_pdf(pdf, 420, 297)  # A3 landscape
    assert pdf_to_png(pdf, png, PNG_QUALITY["2x"]) == 300
    with Image.open(png) as img:
        assert img.mode == "RGB"
        assert abs(img.size[0] - 420 / 25.4 * 300) < 4
        assert abs(img.size[1] - 297 / 25.4 * 300) < 4
        assert round(img.info["dpi"][0]) == 300
        assert img.getpixel((5, 5)) == (255, 255, 255)  # white paper, not transparent
        assert img.getpixel((img.size[0] // 2, 60)) == (0, 0, 0)  # the drawing itself


def test_very_large_pages_are_drawn_at_a_lower_resolution(tmp_path):
    pdf, png = tmp_path / "big.pdf", tmp_path / "big.png"
    make_pdf(pdf, 1600, 600)
    used = pdf_to_png(pdf, png, 300, max_pixels=20_000_000)
    assert used < 300
    with Image.open(png) as img:
        assert img.size[0] * img.size[1] <= 20_000_000


def vector_pdf(path, width_pt, height_pt, content):
    """A one-page PDF whose page is drawn by the given content stream, as CAD exports are (vector lines)."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %g %g] /Contents 4 0 R >>" % (width_pt, height_pt),
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (n, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(bytes(out))


def test_preview_fits_the_box_and_keeps_thin_lines_dark(tmp_path):
    pdf, out = tmp_path / "wide.pdf", tmp_path / "wide.preview.webp"
    w, h = 1373 / 25.4 * 72, 420 / 25.4 * 72
    vector_pdf(pdf, w, h, b"0 G 0.7 w 0 %g m %g %g l S" % (h / 2, w, h / 2))  # a 0.25 mm line: 0.13 px in the preview

    assert pdf_thumbnail(pdf, out, box=(720, 540)) == (720, 220)
    with Image.open(out) as img:
        assert img.format == "WEBP" and img.size == (720, 220)
        gray = img.convert("L")
        assert min(gray.getpixel((360, y)) for y in range(img.size[1])) < 128  # the line is still clearly there
        assert gray.getpixel((5, 5)) > 245  # white paper
