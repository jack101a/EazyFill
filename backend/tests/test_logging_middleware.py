import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.logging_middleware import LoggingMiddleware


def test_logging_middleware_echoes_safe_request_id():
    app = FastAPI()
    app.add_middleware(LoggingMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    response = TestClient(app).get("/ping", headers={"X-Request-ID": "test-request-123"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test-request-123"
    assert response.headers["x-process-time-ms"].isdigit()


def test_logging_middleware_replaces_unsafe_request_id():
    app = FastAPI()
    app.add_middleware(LoggingMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    response = TestClient(app).get("/ping", headers={"X-Request-ID": "bad value\nnext"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad value\nnext"
    assert len(response.headers["x-request-id"]) == 32


def test_logging_middleware_logs_failed_request(caplog):
    app = FastAPI()
    app.add_middleware(LoggingMiddleware)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR, logger="request"):
        try:
            TestClient(app).get("/boom", headers={"X-Request-ID": "boom-1"})
        except RuntimeError:
            pass

    record = next(item for item in caplog.records if item.message == "request_failed")
    assert record.context["request_id"] == "boom-1"
    assert record.context["error_type"] == "RuntimeError"
    assert record.context["path"] == "/boom"
