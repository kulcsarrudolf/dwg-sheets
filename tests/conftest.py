import pytest
from fakes import fake_exporter, fake_planner
from fastapi.testclient import TestClient

from dwg_sheets_to_pdf.web.app import create_app
from dwg_sheets_to_pdf.web.settings import Settings


@pytest.fixture
def make_client(tmp_path):
    """A test client for the web app, with fake CADCraft and settings overrides."""

    def make(planner=None, exporter=None, **settings):
        s = Settings(work_dir=tmp_path / "jobs", **settings)
        return TestClient(create_app(s, planner or fake_planner(), exporter or fake_exporter()))

    return make
