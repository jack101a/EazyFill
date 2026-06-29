from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.paths import get_project_root

router = APIRouter(tags=["public-site"])

_SITE_DIR = (get_project_root() / "docs" / "public-site").resolve()

_PAGES = {
    "/": "index.html",
    "/pricing": "pricing.html",
    "/contact": "contact.html",
    "/privacy": "privacy.html",
    "/privacy-policy.html": "privacy.html",
    "/terms": "terms.html",
    "/terms-and-conditions": "terms.html",
    "/refunds": "refunds.html",
    "/cancellation-refund-policy": "refunds.html",
    "/delivery": "delivery.html",
    "/shipping-delivery-policy": "delivery.html",
}


def public_site_file(route_path: str) -> Path:
    filename = _PAGES.get(route_path)
    if not filename:
        raise HTTPException(status_code=404, detail="page_not_found")
    path = (_SITE_DIR / filename).resolve()
    if not str(path).startswith(str(_SITE_DIR)) or not path.exists():
        raise HTTPException(status_code=404, detail="page_not_found")
    return path


def _html_response(route_path: str) -> FileResponse:
    return FileResponse(str(public_site_file(route_path)), media_type="text/html")


@router.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return _html_response("/")


@router.get("/pricing", include_in_schema=False)
async def pricing() -> FileResponse:
    return _html_response("/pricing")


@router.get("/contact", include_in_schema=False)
async def contact() -> FileResponse:
    return _html_response("/contact")


@router.get("/privacy", include_in_schema=False)
@router.get("/privacy-policy.html", include_in_schema=False)
async def privacy() -> FileResponse:
    return _html_response("/privacy")


@router.get("/terms", include_in_schema=False)
@router.get("/terms-and-conditions", include_in_schema=False)
async def terms() -> FileResponse:
    return _html_response("/terms")


@router.get("/refunds", include_in_schema=False)
@router.get("/cancellation-refund-policy", include_in_schema=False)
async def refunds() -> FileResponse:
    return _html_response("/refunds")


@router.get("/delivery", include_in_schema=False)
@router.get("/shipping-delivery-policy", include_in_schema=False)
async def delivery() -> FileResponse:
    return _html_response("/delivery")
