"""Single-process background scheduler entrypoint.

Run this as a separate container/process so API workers can scale without
running duplicate backup or subscription expiry jobs.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.background_tasks import backup_scheduler, subscription_expiry_loop
from app.core.config import get_settings
from app.core.container import build_container
from app.core.logging import configure_logging


settings = get_settings()
configure_logging(settings=settings)
container = build_container(settings=settings)

logger = logging.getLogger(__name__)


async def run() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    tasks = [
        asyncio.create_task(backup_scheduler(container), name="backup-scheduler"),
        asyncio.create_task(subscription_expiry_loop(container), name="subscription-expiry-loop"),
    ]
    logger.info("scheduler_started", extra={"context": {"tasks": [task.get_name() for task in tasks]}})

    try:
        await stop_event.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("scheduler_stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
