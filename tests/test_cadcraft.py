import json
from pathlib import Path

from dwg_sheets_to_pdf import cadcraft
from dwg_sheets_to_pdf.cadcraft import CadCraft


def export_command(monkeypatch, page_mm):
    monkeypatch.setattr(cadcraft.shutil, "which", lambda exe: "/bin/cadcraft-cli")
    calls = []

    class Proc:
        returncode = 0
        stdout = "{}\n"
        stderr = ""

    monkeypatch.setattr(cadcraft.subprocess, "run", lambda args, **kw: calls.append(args) or Proc())
    CadCraft().export_pdf(Path("in.dwg"), Path("out.pdf"), (0, 0, 52.5, 29.7), 10.0, page_mm)
    (args,) = calls
    cmd = args[args.index("--cmd") + 1]
    name, params = cmd.split(" ", 1)
    assert name == "exportpdf"
    return json.loads(params)


def test_export_fills_the_page_without_margins(monkeypatch):
    params = export_command(monkeypatch, (525.0, 297.0))
    assert params["margins"] == [0, 0, 0, 0]
    assert params["window"] == [[0, 0], [52.5, 29.7]]
    assert params["scale"] == 10.0
    assert (params["width"], params["height"]) == (525.0, 297.0)
    assert params["landscape"] is True


def test_export_portrait_page(monkeypatch):
    params = export_command(monkeypatch, (841.0, 1188.0))
    assert params["landscape"] is False
