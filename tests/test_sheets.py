from dwg_sheets_to_pdf.sheets import Rect, Sheet, duplicates, find_sheets, labels, rectangles, safe_filename


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
        Sheet("A13", Rect(0, 0, 42, 29.7), 100.0, double=True),  # outer + inner frame
        Sheet("A16", Rect(50, 0, 176, 59.4), 200.0),  # single frame
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


def test_double_frame_is_the_page_and_its_outer_line_is_hidden():
    rects = [
        Rect(0, 0, 270, 118.8, "OUT"),  # outer trimming line
        Rect(0, 0, 270, 118.8, "OUT2"),  # the same line drawn twice
        Rect(4, 2, 268, 116.8, "IN"),  # drawn border
    ]
    texts = [text("PL. NR. A07", 260, 5), text("1:200", 250, 5)]
    (sheet,), _ = find_sheets(rects, texts)
    assert sheet.double
    assert sheet.outer_handles == ("OUT", "OUT2")
    plot = sheet.plot(unit_mm=1000)
    assert plot.window == Rect(0, 0, 270, 118.8)
    assert plot.page_mm == (1350.0, 594.0)
    assert plot.hide == ("OUT", "OUT2")


def test_single_frame_gets_margins_and_nothing_hidden():
    rects = [Rect(0, 0, 63, 29.7, "F")]
    texts = [text("PL. NR. A14", 60, 2), text("1:100", 58, 2)]
    (sheet,), _ = find_sheets(rects, texts)
    assert not sheet.double
    plot = sheet.plot(unit_mm=1000)  # 1:100 in metres: 1 unit = 10 mm, so 20 mm = 2 units
    assert plot.window == Rect(-2, -1, 64, 30.7)
    assert plot.page_mm == (660.0, 317.0)
    assert plot.hide == ()
    assert sheet.plot(unit_mm=1000, margins_mm=(0, 0, 0, 0)).page_mm == (630.0, 297.0)


def test_a_box_far_inside_the_frame_is_not_a_second_border():
    rects = [Rect(0, 0, 42, 29.7, "F"), Rect(30, 1, 41, 6, "TITLE")]  # title block box, not a border
    texts = [text("PL. NR. A13", 40, 2), text("1:100", 38, 3)]
    (sheet,), _ = find_sheets(rects, texts)
    assert not sheet.double


def test_page_size_in_millimetre_drawings():
    sheet = Sheet("x", Rect(0, 0, 4200, 2970), 10, double=True)
    assert sheet.plot(unit_mm=1).page_mm == (420.0, 297.0)


def test_safe_filename():
    assert safe_filename("A07") == "A07"
    assert safe_filename("A/7: plan") == "A_7_plan"
    assert safe_filename("...") == "sheet"


def test_sheets_sharing_a_number_get_labels_in_reading_order():
    # Three title blocks say A15 (copied without renumbering), placed out of order on the drawing.
    rects = [Rect(x, 0, x + 9, 9) for x in (0, 20, 40, 60)]
    texts = []
    for x, name in ((40, "A15"), (0, "A15"), (20, "A04"), (60, "A15")):
        texts += [text(f"PL. NR. {name}", x + 5, 5), text("1:100", x + 4, 4)]
    sheets, _ = find_sheets(rects, texts)
    assert [(s.name, s.frame.x0) for s in sheets] == [("A04", 20), ("A15", 0), ("A15", 40), ("A15", 60)]
    assert labels(sheets) == ["A04", "A15-1", "A15-2", "A15-3"]
    assert duplicates(sheets) == {"A15": 3}
    assert labels(sheets[:2]) == ["A04", "A15"]  # a number used once keeps its plain name
