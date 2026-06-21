import asyncio

import pytest
from fastapi import HTTPException

from app.services.solver_service import SolverService


class _FakeCache:
    def get(self, *_args, **_kwargs):
        return None


class _FakeRouter:
    async def solve(self, **_kwargs):
        return {"result": "ABCD", "model_used": "fake"}


def _service() -> SolverService:
    return SolverService(
        workers=1,
        max_pending_jobs=1,
        model_router=_FakeRouter(),
        cache=_FakeCache(),
    )


def test_submit_captcha_rejects_non_captcha_task_type():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(_service().submit_captcha("workflow", "QUJDRA=="))

    assert exc.value.status_code == 400
    assert exc.value.detail == "unsupported captcha task type"
