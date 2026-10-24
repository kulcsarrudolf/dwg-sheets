"""HTML pages, rendered on the server and updated in place with htmx."""

from __future__ import annotations

from importlib.resources import files
from typing import Annotated

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ..raster import PNG_QUALITY
from .i18n import COOKIE, LANGUAGES, negotiate, translator
from .jobs import JobState
from .service import JobError, JobService, file_url, urls

_ONE_YEAR = 365 * 24 * 3600
# Width over height of the box each sheet's preview sits in on the page; must match .card-media in app.css.
PREVIEW_RATIO = 4 / 3


def templates() -> Jinja2Templates:
    t = Jinja2Templates(directory=str(files("dwg_sheets.web").joinpath("templates")))
    # {% trans %} blocks call the per-request gettext/ngettext passed in each render's context.
    t.env.add_extension("jinja2.ext.i18n")
    t.env.policies["ext.i18n.trimmed"] = True
    t.env.filters["num"] = lambda value, t: t.number(value)
    return t


def views_router(service: JobService, settings_view: dict) -> APIRouter:
    router = APIRouter()
    tpl = templates()

    def render(request: Request, name: str, status_code: int = 200, headers: dict | None = None, **context) -> Response:
        lang = negotiate(
            request.query_params.get("lang"), request.cookies.get(COOKIE), request.headers.get("accept-language")
        )
        t = translator(lang)
        response = tpl.TemplateResponse(
            request,
            name,
            {
                "t": t,
                "lang": lang,
                "languages": LANGUAGES,
                "gettext": t.gettext,
                "ngettext": t.ngettext,
                "_": t.gettext,
                "config": settings_view,
                "images": _images_choice(request),
                **context,
            },
            status_code=status_code,
            headers=headers,
        )
        if request.query_params.get("lang") in LANGUAGES:
            response.set_cookie(COOKIE, lang, max_age=_ONE_YEAR, samesite="lax")
        return response

    def is_htmx(request: Request) -> bool:
        return request.headers.get("hx-request") == "true"

    @router.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Response:
        return render(request, "index.html", job=None)

    @router.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, job_id: str) -> Response:
        try:
            job = job_view(service.get(job_id))
        except JobError as e:
            return render(request, "index.html", status_code=e.status, job=None, error=e)
        return render(request, "index.html", job=job)

    @router.get("/jobs/{job_id}/panel", response_class=HTMLResponse)
    def job_panel(request: Request, job_id: str) -> Response:
        try:
            return render(request, "_job.html", job=job_view(service.get(job_id)))
        except JobError as e:
            return render(request, "_error.html", status_code=e.status, error=e)

    @router.post("/jobs", response_class=HTMLResponse)
    async def upload(request: Request, file: UploadFile, images: Annotated[str, Form()] = "none") -> Response:
        try:
            state = await service.start(file, images)
        except JobError as e:
            if is_htmx(request):
                return render(request, "_error.html", status_code=e.status, error=e)
            return render(request, "index.html", status_code=e.status, job=None, error=e)
        if not is_htmx(request):
            return RedirectResponse(f"/jobs/{state.id}", status_code=303)
        return render(request, "_job.html", headers={"HX-Push-Url": f"/jobs/{state.id}"}, job=job_view(state))

    @router.delete("/jobs/{job_id}", response_class=HTMLResponse)
    def delete(request: Request, job_id: str) -> Response:
        try:
            service.delete(job_id)
        except JobError:
            pass  # already gone: the result is the same
        return render(request, "_intro.html", headers={"HX-Push-Url": "/"}, deleted=True)

    return router


def job_view(state: JobState) -> dict:
    """What the job panel shows, worked out once here instead of in the template."""
    sheets = state.sheets
    done = sum(s.status != "pending" for s in sheets)
    failed = sum(s.status == "failed" for s in sheets)
    ready = sum(s.status == "done" for s in sheets)
    return {
        "id": state.id,
        "drawing": state.drawing,
        "status": state.status,
        "running": state.status in ("queued", "reading", "exporting"),
        "error_code": state.error_code,
        "error_params": state.error_params,
        "done": done,
        "failed": failed,
        "total": len(sheets),
        "duplicates": ", ".join(f"{name} ({n}\u00d7)" for name, n in state.duplicates.items()),
        "percent": round(100 * done / len(sheets)) if sheets else 0,
        "zip_url": urls(state.id)["zip"] if state.status == "done" else None,
        "pick_url": urls(state.id)["zip"],  # ?sheet=0&sheet=3 for only some sheets
        "ready": ready,
        "skipped": state.skipped,
        "sheets": [
            {
                "index": i,
                "name": s.label or s.name,
                "scale": s.scale,
                "width": s.page_mm[0],
                "height": s.page_mm[1],
                "status": s.status,
                "url": file_url(state.id, s.file) if s.status == "done" else None,
                "png_url": file_url(state.id, s.png) if s.status == "done" and s.png else None,
                "png_dpi": s.png_dpi,
                "thumb_url": file_url(state.id, s.thumb) if s.status == "done" and s.thumb else None,
                # The page shape: the preview (or its outline while plotting) fills the box's width or height.
                "ratio": f"{s.page_mm[0]:g} / {s.page_mm[1]:g}",
                "fit": "wide" if s.page_mm[0] / s.page_mm[1] >= PREVIEW_RATIO else "tall",
            }
            for i, s in enumerate(sheets)
        ],
    }


def _images_choice(request: Request) -> str:
    """The reader's last choice of images (set by the page in a cookie), or none."""
    choice = request.cookies.get("images", "none")
    return choice if choice in ("none", *PNG_QUALITY) else "none"
