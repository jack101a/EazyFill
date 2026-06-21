"""Standalone solver worker.

Consumes Redis-backed captcha solve jobs created by the API. This lets extra
machines join the worker pool as long as they can reach the configured Redis
endpoint, for example through the private WireGuard VPN.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from typing import Any

from redis import asyncio as redis_async

from app.core.config import get_settings
from app.core.container import build_container
from app.core.logging import configure_logging


settings = get_settings()
configure_logging(settings=settings)
container = build_container(settings=settings)
logger = logging.getLogger(__name__)


def _worker_count() -> int:
    raw = os.getenv("SOLVER_WORKER_CONCURRENCY", os.getenv("QUEUE_WORKERS", "2"))
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 2


async def _publish_result(
    client: redis_async.Redis,
    result_key: str,
    payload: dict[str, Any],
    ttl_seconds: int,
) -> None:
    await client.rpush(result_key, json.dumps(payload, separators=(",", ":")))
    await client.expire(result_key, ttl_seconds)


async def _requeue_or_fail(
    client: redis_async.Redis,
    queue_key: str,
    dead_letter_key: str,
    result_key: str,
    job: dict[str, Any],
    error: Exception,
    worker_id: int,
    result_ttl: int,
) -> None:
    attempt = max(1, int(job.get("attempt") or 1))
    max_attempts = max(1, int(job.get("max_attempts") or os.getenv("SOLVER_JOB_ATTEMPTS", "3") or "3"))
    job["last_error"] = str(error)
    if attempt < max_attempts:
        job["attempt"] = attempt + 1
        await client.rpush(queue_key, json.dumps(job, separators=(",", ":")))
        return

    await client.rpush(dead_letter_key, json.dumps(job, separators=(",", ":")))
    await client.ltrim(dead_letter_key, -1000, -1)
    await _publish_result(
        client,
        result_key,
        {"status": "error", "error": str(error), "worker_id": worker_id, "attempt": attempt},
        result_ttl,
    )


async def _worker_loop(worker_id: int, stop_event: asyncio.Event) -> None:
    client = await container.solver_service._redis_client()
    queue_key = container.solver_service.redis_queue_key
    dead_letter_key = container.solver_service.redis_dead_letter_key
    result_ttl = max(60, int(os.getenv("SOLVER_RESULT_TTL_SECONDS", "120") or "120"))
    logger.info("solver_worker_started", extra={"context": {"worker_id": worker_id, "queue": queue_key}})

    while not stop_event.is_set():
        try:
            item = await client.blpop(queue_key, timeout=5)
            if not item:
                continue
            _key, raw = item
            job = json.loads(raw)
            request_id = str(job.get("request_id") or "")
            result_key = container.solver_service.redis_result_key(request_id)
            if not request_id:
                logger.warning("solver_worker_invalid_job", extra={"context": {"worker_id": worker_id}})
                continue

            try:
                result = await container.solver_service.solve_direct(
                    task_type=str(job.get("task_type") or ""),
                    payload_base64=str(job.get("payload_base64") or ""),
                    domain=job.get("domain"),
                    field_name=job.get("field_name"),
                    model_filename=job.get("model_filename"),
                )
                await _publish_result(
                    client,
                    result_key,
                    {"status": "ok", "payload": result, "worker_id": worker_id},
                    result_ttl,
                )
                logger.info(
                    "solver_worker_job_done",
                    extra={"context": {"worker_id": worker_id, "request_id": request_id, "model_used": result.get("model_used")}},
                )
            except Exception as exc:
                logger.exception(
                    "solver_worker_job_failed",
                    extra={"context": {"worker_id": worker_id, "request_id": request_id, "error": str(exc)}},
                )
                await _requeue_or_fail(
                    client,
                    queue_key,
                    dead_letter_key,
                    result_key,
                    job,
                    exc,
                    worker_id,
                    result_ttl,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("solver_worker_loop_failed", extra={"context": {"worker_id": worker_id, "error": str(exc)}})
            await asyncio.sleep(1)


async def run() -> None:
    if not container.solver_service.uses_remote_queue():
        raise RuntimeError("Set SOLVER_QUEUE_BACKEND=redis before starting app.worker")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: stop_event.set())

    tasks = [asyncio.create_task(_worker_loop(index, stop_event), name=f"solver-worker-{index}") for index in range(_worker_count())]
    try:
        await stop_event.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await container.solver_service.stop()
        logger.info("solver_worker_stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
