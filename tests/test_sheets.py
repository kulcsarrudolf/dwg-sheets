from dwg_sheets_to_pdf.sheets import Rect, Sheet, find_sheets, rectangles, safe_filename


def pline(points, closed=True, bulge=0.0):
    return {
        "type": "Polyline",
        "geometry": {
            "closed": closed,
            "vertices": [{"p": {"x": x, "y": y}, "bulge": bulge} for x, y in points],
        },
    }


def box(x0, y0, x1, y1, **kw):
    return pline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], **kw)


def text(s, x, y):
    return {"text": s, "at": [x, y]}


def test_rectangles_keeps_only_closed_axis_aligned_boxes():
    entities = [
        box(0, 0, 10, 5),
        box(0, 0, 10, 5, closed=False),  # open
        box(0, 0, 10, 5, bulge=0.5),  # arcs
        pline([(0, 0), (10, 1), (10, 5), (0, 5)]),  # skewed
        pline([(0, 0), (10, 0), (10, 5), (0, 5), (0, 0)], closed=False),  # closed by repeating the first point
        pline([(0, 0), (10, 0), (5, 5)]),  # triangle
    ]
    assert rectangles(entities) == [Rect(0, 0, 10, 5), Rect(0, 0, 10, 5)]


def test_find_sheets_matches_frame_and_nearest_scale():
    rects = [
        Rect(0, 0, 42, 29.7),  # outer frame of A13
        Rect(2, 1, 41, 28.7),  # inner frame of A13
        Rect(30, 1, 41, 6),  # title block box of A13
        Rect(50, 0, 176, 59.4),  # frame of A16
        Rect(-10, -10, 200, 100),  # border around everything: holds two title blocks
    ]
    texts = [
        text("PL. NR.\nA13", 40, 2),
        text("SCARA:\n\n1:100", 38, 3),
        text("detail 1:20", 5, 25),  # another scale inside A13, farther from its title block
        text("PL. NR.\nA16", 170, 2),
        text("SCARA 1:200", 168, 3),
        text("unrelated", 100, 50),
    ]
    sheets, skipped = find_sheets(rects, texts)
    assert skipped == []
    assert sheets == [
        Sheet("A13", Rect(0, 0, 42, 29.7), 100.0),
        Sheet("A16", Rect(50, 0, 176, 59.4), 200.0),
    ]


def test_find_sheets_reports_missing_frame_and_scale():
    rects = [Rect(0, 0, 10, 10)]
    texts = [text("PL. NR. A01", 5, 5), text("PL. NR. A02", 50, 50)]
    sheets, skipped = find_sheets(rects, texts)
    assert sheets == []
    assert [(s.name, s.reason) for s in skipped] == [
        ("A01", "no 1:N scale inside its frame"),
        ("A02", "no frame around its title block"),
    ]


def test_sheets_sorted_naturally():
    rects = [Rect(i * 10, 0, i * 10 + 9, 9) for i in range(3)]
    texts = []
    for i, name in enumerate(["A10", "A2", "A1"]):
        texts += [text(f"PL. NR. {name}", i * 10 + 5, 5), text("1:100", i * 10 + 4, 4)]
    sheets, _ = find_sheets(rects, texts)
    assert [s.name for s in sheets] == ["A1", "A2", "A10"]


def test_custom_title_pattern():
    rects = [Rect(0, 0, 10, 10)]
    texts = [text("Sheet no: S-01", 5, 5), text("Scale 1:50", 4, 4)]
    sheets, _ = find_sheets(rects, texts, title_pattern=r"Sheet no:\s*(\S+)")
    assert [(s.name, s.scale) for s in sheets] == [("S-01", 50.0)]


def test_page_size_at_true_scale():
    sheet = Sheet("A07", Rect(0, 0, 270, 118.8), 200)
    assert sheet.page_size_mm(unit_mm=1000) == (1350.0, 594.0)  # metres
    assert Sheet("x", Rect(0, 0, 4200, 2970), 10).page_size_mm(unit_mm=1) == (420.0, 297.0)  # mm


def test_safe_filename():
    assert safe_filename("A07") == "A07"
    assert safe_filename("A/7: plan") == "A_7_plan"
    assert safe_filename("...") == "sheet"
