"""The HTML pages: server-rendered, updated in place by htmx."""

import io
import re
import threading
import zipfile

from fakes import PNG, fake_exporter, fake_planner, wait

HX = {"HX-Request": "true"}


def html_upload(client, name="Project.dwg", data=b"AC1032 drawing", headers=HX, images=None, **kw):
    files = {"file": (name, io.BytesIO(data), "application/octet-stream")}
    form = {"images": images} if images else None
    return client.post("/jobs", files=files, data=form, headers=headers, follow_redirects=False, **kw)


def job_id_from(response):
    return response.headers["HX-Push-Url"].rsplit("/", 1)[1]


def test_language_from_query_then_cookie_then_browser(make_client):
    with make_client() as c:
        r = c.get("/?lang=ro")
        assert '<html lang="ro">' in r.text
        assert "Trageti aici un fisier .dwg sau .dxf" in r.text
        assert 'aria-current="true">RO<' in r.text.replace("\n", "").replace("  ", "")
        assert r.cookies.get("lang") == "ro"
        assert '<html lang="ro">' in c.get("/").text  # remembered
        c.cookies.clear()
        r = c.get("/", headers={"Accept-Language": "hu-HU,hu;q=0.9"})
        assert '<html lang="hu">' in r.text and "Húzzon ide egy .dwg vagy .dxf fájlt" in r.text
        assert '<html lang="en">' in c.get("/", headers={"Accept-Language": "de"}).text


def test_upload_shows_the_job_and_stops_polling_when_done(make_client):
    with make_client(planner=fake_planner(skipped=[("A99", "x", "no_frame")])) as c:
        r = html_upload(c)
        assert r.status_code == 200
        job_id = job_id_from(r)
        assert r.headers["HX-Push-Url"] == f"/jobs/{job_id}"
        assert "<html" not in r.text  # a fragment, swapped into the page
        wait(c, job_id)

        panel = c.get(f"/jobs/{job_id}/panel?lang=en", headers=HX).text
        assert "hx-trigger" not in panel  # finished: no more polling
        assert "Done. Every sheet is ready." in panel
        assert "2 of 2 sheets" in panel and "2 sheets" in panel
        assert panel.count(f"/api/jobs/{job_id}/files/") == 6  # preview, open and download for each sheet
        assert ">PNG<" not in panel  # no images asked for
        assert f"/api/jobs/{job_id}/zip" in panel
        assert "Skipped A99: no frame around its title block" in panel
        assert "420 &times; 297" in panel

        ro = c.get(f"/jobs/{job_id}?lang=ro").text  # the job has its own page, in any language
        assert "<html" in ro and "Gata. Toate plansele sunt pregatite." in ro and "2 planse" in ro
        assert "Omisa A99: nu are chenar in jurul cartusului" in ro


def test_running_job_keeps_polling(make_client):
    gate = threading.Event()

    def slow_exporter(p, options, on_done):
        gate.wait(5)
        return fake_exporter()(p, options, on_done)

    with make_client(exporter=slow_exporter) as c:
        job_id = job_id_from(html_upload(c))
        panel = c.get(f"/jobs/{job_id}/panel", headers=HX).text
        assert f'hx-get="/jobs/{job_id}/panel"' in panel
        gate.set()
        wait(c, job_id)


def test_upload_errors_are_translated(make_client):
    with make_client(max_upload_mb=1) as c:
        c.cookies.set("lang", "ro")
        r = html_upload(c, "notes.txt", b"AC10")
        assert r.status_code == 400
        assert "Alegeti un fisier .dwg sau .dxf." in r.text
        c.cookies.set("lang", "hu")
        r = html_upload(c, "big.dwg", b"AC10" + b"x" * (1024 * 1024))
        assert r.status_code == 413
        assert "A fájl nagyobb, mint 1 MB." in r.text


def test_failed_job_message_is_translated(make_client):
    with make_client(planner=fake_planner(names=())) as c:
        job_id = job_id_from(html_upload(c))
        wait(c, job_id)
        assert "Nu s-au gasit planse." in c.get(f"/jobs/{job_id}/panel?lang=ro", headers=HX).text


def test_unknown_job_page(make_client):
    with make_client() as c:
        r = c.get("/jobs/" + "0" * 32 + "?lang=hu")
        assert r.status_code == 404
        assert "Ez az export már nem létezik." in r.text


def test_upload_without_javascript_redirects_to_the_job_page(make_client):
    with make_client() as c:
        r = html_upload(c, headers={})
        assert r.status_code == 303
        assert re.fullmatch(r"/jobs/[0-9a-f]{32}", r.headers["location"])


def test_delete_returns_the_intro(make_client, tmp_path):
    with make_client() as c:
        job_id = job_id_from(html_upload(c))
        wait(c, job_id)
        r = c.delete(f"/jobs/{job_id}", headers=HX)
        assert r.status_code == 200 and r.headers["HX-Push-Url"] == "/"
        assert "The files were deleted from the server." in r.text
        assert not (tmp_path / "jobs" / job_id).exists()
        assert c.get(f"/jobs/{job_id}").status_code == 404


def test_sheets_sharing_a_number_all_export_and_are_flagged(make_client):
    with make_client(planner=fake_planner(names=("A04", "A15", "A15", "A15"))) as c:
        job_id = job_id_from(html_upload(c))
        job = wait(c, job_id)
        assert job["status"] == "done" and job["error_code"] is None
        assert [s["label"] for s in job["sheets"]] == ["A04", "A15-1", "A15-2", "A15-3"]
        assert len({s["file"] for s in job["sheets"]}) == 4  # no file overwrites another
        assert all(s["status"] == "done" for s in job["sheets"])
        assert job["duplicates"] == {"A15": 3}

        panel = c.get(f"/jobs/{job_id}/panel?lang=en", headers=HX).text
        assert "Done. Every sheet is ready." in panel and "4 of 4 sheets" in panel
        assert "Several sheets share a sheet number: A15 (3\u00d7)." in panel
        assert ">A15-3<" in panel
        assert (
            "Mai multe planse au acelasi numar: A15 (3\u00d7)."
            in c.get(f"/jobs/{job_id}/panel?lang=ro", headers=HX).text
        )


def test_partial_failure_says_so(make_client):
    with make_client(exporter=fake_exporter(fail={"A14"})) as c:
        job_id = job_id_from(html_upload(c))
        wait(c, job_id)
        panel = c.get(f"/jobs/{job_id}/panel?lang=en", headers=HX).text
        assert "Done, but some sheets could not be exported." in panel
        assert "Every sheet is ready" not in panel
        assert "1 of 2 sheets could not be exported." in panel


def test_png_images_on_request(make_client):
    with make_client() as c:
        job_id = job_id_from(html_upload(c, images="2x"))
        job = wait(c, job_id)
        assert job["images"] == "2x"
        assert [s["png"] for s in job["sheets"]] == ["Project - A13.png", "Project - A14.png"]
        assert [s["png_dpi"] for s in job["sheets"]] == [300, 300]

        png = c.get(job["sheets"][0]["png_url"] + "?download=1")
        assert png.status_code == 200 and png.headers["content-type"] == "image/png"
        assert png.content == PNG

        panel = c.get(f"/jobs/{job_id}/panel", headers=HX).text
        assert panel.count(">PNG<") == 2 and "(300 dpi)" in panel
        names = zipfile.ZipFile(io.BytesIO(c.get(job["zip_url"]).content)).namelist()
        assert sorted(names) == ["Project - A13.pdf", "Project - A13.png", "Project - A14.pdf", "Project - A14.png"]


def test_unknown_image_choice_is_refused(make_client):
    with make_client() as c:
        r = html_upload(c, images="8x")
        assert r.status_code == 400 and "PDF + PNG 2×" in r.text


def test_image_choice_is_remembered_in_the_form(make_client):
    with make_client() as c:
        assert 'value="none" checked' in c.get("/").text
        c.cookies.set("images", "2x")
        assert 'value="2x" checked' in c.get("/").text
        c.cookies.set("images", "nonsense")
        assert 'value="none" checked' in c.get("/").text


def test_sheets_show_previews_and_can_be_ticked(make_client):
    with make_client() as c:
        job_id = job_id_from(html_upload(c))
        wait(c, job_id)
        panel = c.get(f"/jobs/{job_id}/panel?lang=en", headers=HX).text
        assert f'<img src="/api/jobs/{job_id}/files/Project - A13.preview.webp"' in panel
        assert f'id="pick-form" action="/api/jobs/{job_id}/zip" method="get"' in panel
        assert 'name="sheet" value="0"' in panel and 'name="sheet" value="1"' in panel
        assert 'class="card-link" href="/api/jobs/' in panel and 'target="_blank"' in panel  # a click opens the PDF
        assert "Download selected (ZIP)" in panel
        assert 'style="aspect-ratio: 420 / 297"' in panel and 'class="paper wide"' in panel


def test_sheets_still_plotting_cannot_be_ticked(make_client):
    release = threading.Event()

    def slow_exporter(p, options, on_done):
        for r in p.results:
            release.wait(5)
            r.file.parent.mkdir(parents=True, exist_ok=True)
            r.file.write_bytes(b"%PDF")
            on_done(r)
        return p.results

    with make_client(exporter=slow_exporter) as c:
        job_id = job_id_from(html_upload(c))
        for _ in range(200):
            panel = c.get(f"/jobs/{job_id}/panel?lang=en", headers=HX).text
            if "card is-pending" in panel:
                break
        assert 'name="sheet"' not in panel and ">Plotting<" in panel
        assert "data-select-all disabled" in panel
        release.set()
        wait(c, job_id)
