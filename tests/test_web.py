import base64
import io
import re
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dwg_sheets_to_pdf.cadcraft import CadCraftError
from dwg_sheets_to_pdf.export import Plan, SheetResult
from dwg_sheets_to_pdf.sheets import Rect, Sheet, Skipped
from dwg_sheets_to_pdf.web.app import create_app
from dwg_sheets_to_pdf.web.settings import Settings

PDF = b"%PDF-1.7 fake\n"


def fake_planner(names=("A13", "A14"), skipped=()):
    def planner(drawing: Path, out_dir: Path, options, stem: str) -> Plan:
        assert drawing.read_bytes().startswith(b"AC10")
        sheets = [Sheet(n, Rect(0, 0, 42, 29.7), 100.0, double=(i == 0)) for i, n in enumerate(names)]
        results = [
            SheetResult(n, 100.0, (420.0, 297.0), i == 0, out_dir / f"{stem} - {n}.pdf") for i, n in enumerate(names)
        ]
        return Plan(drawing, results, [Skipped(*s) for s in skipped], sheets)

    return planner


def fake_exporter(fail=()):
    def exporter(p: Plan, options, on_done):
        for r in p.results:
            if r.name in fail:
                r.error = "plot failed"
            else:
                r.file.parent.mkdir(parents=True, exist_ok=True)
                r.file.write_bytes(PDF)
            on_done(r)
        return p.results

    return exporter


@pytest.fixture
def make_client(tmp_path):
    def make(planner=None, exporter=None, **settings):
        s = Settings(work_dir=tmp_path / "jobs", **settings)
        app = create_app(s, planner or fake_planner(), exporter or fake_exporter())
        return TestClient(app)

    return make


def upload(client, name="Project.dwg", data=b"AC1032 drawing", **kw):
    return client.post("/api/jobs", files={"file": (name, io.BytesIO(data), "application/octet-stream")}, **kw)


def wait(client, job_id, **kw):
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}", **kw).json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_page_and_health(make_client):
    with make_client(max_upload_mb=7, job_ttl_minutes=15) as c:
        page = c.get("/")
        assert page.status_code == 200
        assert c.get("/healthz").json()["status"] == "ok"


def test_upload_exports_every_sheet(make_client):
    with make_client(planner=fake_planner(skipped=[("A99", "no frame around its title block", "no_frame")])) as c:
        r = upload(c)
        assert r.status_code == 202
        job = wait(c, r.json()["id"])
        assert job["status"] == "done"
        assert job["error"] is None
        assert [(s["name"], s["status"], s["double"]) for s in job["sheets"]] == [
            ("A13", "done", True),
            ("A14", "done", False),
        ]
        assert job["skipped"] == [{"name": "A99", "reason": "no frame around its title block", "code": "no_frame"}]

        pdf = c.get(job["sheets"][0]["url"])
        assert pdf.status_code == 200 and pdf.content == PDF
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.headers["content-disposition"].startswith("inline")
        assert c.get(job["sheets"][0]["url"] + "?download=1").headers["content-disposition"].startswith("attachment")

        z = c.get(job["zip_url"])
        assert z.status_code == 200
        assert z.headers["content-disposition"] == "attachment; filename*=utf-8''Project%20-%20PDF.zip"
        assert sorted(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) == ["Project - A13.pdf", "Project - A14.pdf"]


def test_partial_failure_keeps_the_good_sheets(make_client):
    with make_client(exporter=fake_exporter(fail={"A14"})) as c:
        job = wait(c, upload(c).json()["id"])
        assert job["status"] == "done"
        assert job["error"] == "1 of 2 sheet(s) could not be exported."
        assert (job["error_code"], job["error_params"]) == ("partial", {"failed": 1, "total": 2})
        assert [s["status"] for s in job["sheets"]] == ["done", "failed"]
        assert job["sheets"][1]["url"] is None


def test_no_sheets_found(make_client):
    with make_client(planner=fake_planner(names=())) as c:
        job = wait(c, upload(c).json()["id"])
        assert job["status"] == "failed"
        assert "No sheets found" in job["error"]
        assert job["error_code"] == "no_sheets"
        assert job["zip_url"] is None


def test_unreadable_drawing(make_client):
    def planner(*args):
        raise CadCraftError("bad file")

    with make_client(planner=planner) as c:
        job = wait(c, upload(c).json()["id"])
        assert job["status"] == "failed"
        assert job["error"] == "The drawing could not be read: bad file"
        assert job["error_code"] == "unreadable"


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [("notes.txt", b"AC10", 400), ("empty.dwg", b"", 400), ("big.dwg", b"AC10" + b"x" * (1024 * 1024), 413)],
)
def test_rejected_uploads(make_client, tmp_path, name, data, code):
    with make_client(max_upload_mb=1) as c:
        r = upload(c, name, data)
        assert r.status_code == code
        assert (
            r.json()["detail"]["code"]
            == {400: "bad_type" if name.endswith(".txt") else "empty", 413: "too_large"}[code]
        )
    assert list((tmp_path / "jobs").iterdir()) == []  # nothing left on disk


def test_only_listed_files_can_be_downloaded(make_client):
    with make_client() as c:
        job = wait(c, upload(c).json()["id"])
        base = f"/api/jobs/{job['id']}"
        assert c.get(f"{base}/pdf/job.json").status_code == 404
        assert c.get(f"{base}/pdf/..%2Fjob.json").status_code == 404
        assert c.get("/api/jobs/not-a-job").status_code == 404
        assert c.get("/api/jobs/" + "0" * 32).status_code == 404


def test_delete_removes_the_files(make_client, tmp_path):
    with make_client() as c:
        job = wait(c, upload(c).json()["id"])
        assert c.delete(f"/api/jobs/{job['id']}").status_code == 204
        assert c.get(f"/api/jobs/{job['id']}").status_code == 404
        assert not (tmp_path / "jobs" / job["id"]).exists()


def test_expired_jobs_are_purged(make_client):
    with make_client(job_ttl_minutes=1) as c:
        job = wait(c, upload(c).json()["id"])
        store = c.app.state.store
        assert store.purge_expired(now=time.time() + 30) == 0
        assert store.purge_expired(now=time.time() + 120) == 1
        assert c.get(f"/api/jobs/{job['id']}").status_code == 404


def test_password(make_client):
    with make_client(password="s3cret") as c:
        assert c.get("/").status_code == 401
        assert c.get("/healthz").status_code == 200  # health checks stay open for the container platform
        good = {"Authorization": "Basic " + base64.b64encode(b"anyone:s3cret").decode()}
        bad = {"Authorization": "Basic " + base64.b64encode(b"anyone:nope").decode()}
        assert c.get("/", headers=bad).status_code == 401
        assert c.get("/", headers=good).status_code == 200
        assert upload(c, headers=good).status_code == 202


def test_settings_from_env(tmp_path):
    s = Settings.from_env(
        {"WORK_DIR": str(tmp_path), "MAX_UPLOAD_MB": "5", "JOB_TTL_MINUTES": "9", "APP_PASSWORD": "pw"}
    )
    assert (s.work_dir, s.max_upload_mb, s.job_ttl_minutes, s.password) == (tmp_path, 5, 9, "pw")
    assert Settings.from_env({"WORK_DIR": str(tmp_path)}).password is None


def test_every_language_has_every_message():
    """The page's EN, RO and HU message tables must have the same keys, and RO has no diacritics."""
    html = (Path(__file__).parents[1] / "src/dwg_sheets_to_pdf/web/static/index.html").read_text(encoding="utf-8")
    table = html[html.index("const MESSAGES = {") : html.index("const LANGS")]
    blocks = re.split(r"^  (en|ro|hu): \{$", table, flags=re.M)
    langs = dict(zip(blocks[1::2], blocks[2::2], strict=True))
    assert set(langs) == {"en", "ro", "hu"}
    plural_forms = {"zero", "one", "two", "few", "many", "other"}  # each language has its own
    keys = {
        lang: set(re.findall(r'(?:^|[,{]\s*)"?([\w.]+)"?:\s', body, flags=re.M)) - plural_forms
        for lang, body in langs.items()
    }
    assert keys["ro"] == keys["en"]
    assert keys["hu"] == keys["en"]
    assert len(keys["en"]) > 40
    assert not re.search(
        r"[\u0102\u0103\u00c2\u00e2\u00ce\u00ee\u0218\u0219\u021a\u021b\u015e\u015f\u0162\u0163]", langs["ro"]
    )
    assert not re.search(r"\\u0(102|103|0c2|0e2|0ce|0ee|218|219|21a|21b)", langs["ro"])


def test_page_serves_config(make_client):
    with make_client(max_upload_mb=7, job_ttl_minutes=15) as c:
        assert "const CONFIG = { maxUploadMb: 7, ttlMinutes: 15 };" in c.get("/").text
