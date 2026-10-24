import json
from pathlib import Path

from dwg_sheets import cadcraft
from dwg_sheets.cadcraft import CadCraft


def export_commands(monkeypatch, page_mm, hide=()):
    monkeypatch.setattr(cadcraft.shutil, "which", lambda exe: "/bin/cadcraft-cli")
    calls = []

    class Proc:
        returncode = 0
        stdout = "{}\n"
        stderr = ""

    monkeypatch.setattr(cadcraft.subprocess, "run", lambda args, **kw: calls.append(args) or Proc())
    CadCraft().export_pdf(Path("in.dwg"), Path("out.pdf"), (0, 0, 52.5, 29.7), 10.0, page_mm, hide)
    (args,) = calls  # one CADCraft session, so erasing never touches the saved drawing
    assert "--save" not in args
    cmds = [args[i + 1] for i, a in enumerate(args) if a == "--cmd"]
    return [(c.split(" ", 1)[0], json.loads(c.split(" ", 1)[1])) for c in cmds]


def export_command(monkeypatch, page_mm):
    ((name, params),) = export_commands(monkeypatch, page_mm)
    assert name == "exportpdf"
    return params


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


def test_export_erases_hidden_lines_first(monkeypatch):
    cmds = export_commands(monkeypatch, (525.0, 297.0), hide=("1A", "1B"))
    assert [name for name, _ in cmds] == ["erase", "exportpdf"]
    assert cmds[0][1] == {"handles": ["1A", "1B"]}
