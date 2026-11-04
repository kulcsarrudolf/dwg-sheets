"""What a drawing was read with, shown on the page and changed from it without uploading again."""

import io

from fakes import fake_planner, wait

from dwg_sheets.profile import Profile

HX = {"HX-Request": "true"}


def upload(client, **form):
    files = {"file": ("Project.dwg", io.BytesIO(b"AC1032 drawing"), "application/octet-stream")}
    return client.post("/api/jobs", files=files, data=form or None)


def test_the_job_reports_what_it_was_read_with(make_client):
    ai = Profile(
        title_pattern=r"Sheet no:\s*(\S+)",
        units="mm",
        patterns_from="ai",
        units_from="frames",
        example="Sheet no: A13",
        ai_model="x/model",
        ai_status="improved",
        ai_cost_usd=0.002,
    )
    with make_client(planner=fake_planner(profile=ai)) as c:
        job = wait(c, upload(c).json()["id"])
        assert job["profile"]["patterns_from"] == "ai"
        assert job["profile"]["ai_cost_usd"] == 0.002
        page = c.get(f"/jobs/{job['id']}").text
        assert "<code>Sheet no: A13</code>" in page
        assert "found by AI" in page
        assert "from the frame sizes" in page
        assert "20, 10, 10, 10 mm" in page
        assert 'value="Sheet no:\\s*(\\S+)"' in page  # the form starts from what was used


def test_settings_given_on_upload_reach_the_planner(make_client):
    seen = []
    with make_client(planner=fake_planner(seen=seen)) as c:
        r = upload(c, title_pattern=r"Sheet (\S+)", units="cm", margins="5,5,5,5")
        job = wait(c, r.json()["id"])
        assert job["request"] == {"title_pattern": r"Sheet (\S+)", "units": "cm", "margins_mm": [5.0, 5.0, 5.0, 5.0]}
        (options,) = seen
        assert (options.title_pattern, options.scale_pattern, options.units, options.margins_mm) == (
            r"Sheet (\S+)",
            None,
            "cm",
            (5.0, 5.0, 5.0, 5.0),
        )
        assert upload(c, title_pattern="Sheet (").json()["detail"]["code"] == "bad_pattern"
        assert upload(c, units="ft").json()["detail"]["code"] == "bad_units"
        assert upload(c, margins="1,2").json()["detail"]["code"] == "bad_margins"


def test_the_form_exports_again_with_new_settings(make_client):
    seen = []
    with make_client(planner=fake_planner(seen=seen)) as c:
        job_id = upload(c).json()["id"]
        wait(c, job_id)
        old_pdf = c.get(f"/api/jobs/{job_id}").json()["sheets"][0]["url"]
        c.get(f"/api/jobs/{job_id}/zip")  # a ZIP of the old files, which must not survive

        r = c.post(
            f"/jobs/{job_id}/settings",
            data={"title_pattern": r"Sheet (\S+)", "scale_pattern": "", "units": "mm", "margins": "0,0,0,0"},
            headers=HX,
        )
        assert r.status_code == 200
        assert '<section class="job"' in r.text
        job = wait(c, job_id)
        assert job["status"] == "done"
        assert job["profile"]["patterns_from"] == "user"
        assert seen[-1].title_pattern == r"Sheet (\S+)" and seen[-1].units == "mm"
        assert c.get(old_pdf).status_code == 200  # the same file name, exported again
        assert not list((c.app.state.store.dir(job_id)).glob("sheets*.zip"))

        # Back to automatic drops every setting.
        c.post(f"/jobs/{job_id}/settings", data={"title_pattern": "ignored", "auto": "1"}, headers=HX)
        assert wait(c, job_id)["request"] == {}
        assert seen[-1].title_pattern is None and seen[-1].units == "auto"


def test_a_bad_pattern_keeps_what_was_typed(make_client):
    with make_client() as c:
        job_id = upload(c).json()["id"]
        wait(c, job_id)
        r = c.post(f"/jobs/{job_id}/settings?lang=ro", data={"title_pattern": "PL (NR", "units": "auto"}, headers=HX)
        assert r.status_code == 400
        assert "Modelul nu este o expresie regulata valida" in r.text
        assert 'value="PL (NR"' in r.text
        assert '<details class="profile" open>' in r.text
        assert c.get(f"/api/jobs/{job_id}").json()["status"] == "done"  # nothing was started


def test_a_running_job_cannot_start_over(make_client):
    with make_client() as c:
        job_id = upload(c).json()["id"]
        wait(c, job_id)
        store = c.app.state.store
        state = store.load(job_id)
        state.status = "exporting"
        store.save(state)
        r = c.post(f"/api/jobs/{job_id}/rerun", data={"units": "m"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "busy"
        assert c.post("/api/jobs/" + "0" * 32 + "/rerun").status_code == 404


def test_no_sheets_opens_the_settings(make_client):
    with make_client(planner=fake_planner(names=())) as c:
        job_id = upload(c).json()["id"]
        wait(c, job_id)
        page = c.get(f"/jobs/{job_id}/panel", headers=HX).text
        assert '<details class="profile" open>' in page


def test_page_without_javascript_redirects_after_the_form(make_client):
    with make_client() as c:
        job_id = upload(c).json()["id"]
        wait(c, job_id)
        r = c.post(f"/jobs/{job_id}/settings", data={"units": "cm"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == f"/jobs/{job_id}"
