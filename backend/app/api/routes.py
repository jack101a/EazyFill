"""Deprecated v1 API route composition.

The user-centered extension uses /v2 exclusively. Keep this router mounted
without routes for a transition period so legacy paths return 404 instead of
importing retired server-owned extension logic.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["v1"])
