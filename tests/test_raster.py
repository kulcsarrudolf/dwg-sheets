from PIL import Image

from dwg_sheets_to_pdf.raster import PNG_QUALITY, pdf_to_png


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
