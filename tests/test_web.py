import base64
import io
import time
import zipfile

import pytest
from fakes import PDF, WEBP, fake_exporter, fake_planner, wait

from dwg_sheets_to_pdf.cadcraft import CadCraftError
from dwg_sheets_to_pdf.web.settings import Settings


def upload(client, name="Project.dwg", data=b"AC1032 drawing", **kw):
    return client.post("/api/jobs", files={"file": (name, io.BytesIO(data), "application/octet-stream")}, **kw)


def test_page_and_health(make_client):
    with make_client(max_upload_mb=7, job_ttl_minutes=15) as c:
        page = c.get("/")
        assert page.status_code == 200
        assert "Up to 7 MB." in page.text
        assert "after 15 minutes" in page.text
        assert c.get("/healthz").json()["status"] == "ok"
        assert c.get("/static/app.css").status_code == 200
        assert c.get("/static/vendor/htmx-2.0.11.min.js").status_code == 200


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


def test_previews_are_served_but_not_zipped(make_client):
    with make_client() as c:
        job = wait(c, upload(c).json()["id"])
        s = job["sheets"][0]
        assert s["thumb"] == "Project - A13.preview.webp"
        r = c.get(s["thumb_url"])
        assert r.status_code == 200 and r.content == WEBP
        assert r.headers["content-type"] == "image/webp"
        assert "max-age" in r.headers["cache-control"]
        names = zipfile.ZipFile(io.BytesIO(c.get(job["zip_url"]).content)).namelist()
        assert not any(n.endswith(".webp") for n in names)


def test_zip_of_selected_sheets(make_client):
    with make_client(planner=fake_planner(names=("A13", "A14", "A15"))) as c:
        job = wait(c, upload(c).json()["id"])
        z = c.get(job["zip_url"], params={"sheet": [2, 0, 2]})
        assert z.status_code == 200
        assert z.headers["content-disposition"] == "attachment; filename*=utf-8''Project%20-%20PDF%20%282%29.zip"
        assert sorted(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) == ["Project - A13.pdf", "Project - A15.pdf"]

        # Indices that are out of range are ignored; none left is not found.
        assert c.get(job["zip_url"], params={"sheet": [1, 99]}).status_code == 200
        assert c.get(job["zip_url"], params={"sheet": [99]}).status_code == 404
        assert c.get(job["zip_url"], params={"sheet": ["x"]}).status_code == 422


def test_zip_of_selected_sheets_skips_failed_ones(make_client):
    with make_client(exporter=fake_exporter(fail={"A14"})) as c:
        job = wait(c, upload(c).json()["id"])
        z = c.get(job["zip_url"], params={"sheet": [0, 1]})
        assert zipfile.ZipFile(io.BytesIO(z.content)).namelist() == ["Project - A13.pdf"]
        assert c.get(job["zip_url"], params={"sheet": [1]}).status_code == 404
