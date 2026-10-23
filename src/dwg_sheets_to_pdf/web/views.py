"""HTML pages, rendered on the server and updated in place with htmx."""

from __future__ import annotations

from importlib.resources import files

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .i18n import COOKIE, LANGUAGES, negotiate, translator
from .jobs import JobState
from .service import JobError, JobService, pdf_url, urls

_ONE_YEAR = 365 * 24 * 3600
OUTLINE_BOX = (60, 42)  # px: the largest page outline fits this box; the others use the same scale


def templates() -> Jinja2Templates:
    t = Jinja2Templates(directory=str(files("dwg_sheets_to_pdf.web").joinpath("templates")))
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
    async def upload(request: Request, file: UploadFile) -> Response:
        try:
            state = await service.start(file)
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
    max_w = max((s.page_mm[0] for s in sheets), default=1)
    max_h = max((s.page_mm[1] for s in sheets), default=1)
    k = min(OUTLINE_BOX[0] / max_w, OUTLINE_BOX[1] / max_h)
    return {
        "id": state.id,
        "drawing": state.drawing,
        "status": state.status,
        "running": state.status in ("queued", "reading", "exporting"),
        "error_code": state.error_code,
        "error_params": state.error_params,
        "done": done,
        "total": len(sheets),
        "percent": round(100 * done / len(sheets)) if sheets else 0,
        "zip_url": urls(state.id)["zip"] if state.status == "done" else None,
        "skipped": state.skipped,
        "sheets": [
            {
                "name": s.name,
                "scale": s.scale,
                "width": s.page_mm[0],
                "height": s.page_mm[1],
                "double": s.double,
                "status": s.status,
                "url": pdf_url(state.id, s.file) if s.status == "done" else None,
                "outline": (max(4, round(s.page_mm[0] * k)), max(4, round(s.page_mm[1] * k))),
            }
            for s in sheets
        ],
    }
