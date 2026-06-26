"""Shared background loops for API and scheduler entrypoints."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.core.db import get_session

logger = logging.getLogger(__name__)


def _redis_lock_enabled(container) -> bool:
    redis_cfg = getattr(getattr(container, "settings", None), "redis", None)
    return bool(getattr(redis_cfg, "enabled", False))


async def _claim_redis_lock(container, name: str, ttl_seconds: int) -> tuple[object | None, str, str, bool]:
    if not _redis_lock_enabled(container):
        return None, "", "", True
    try:
        import redis.asyncio as redis

        redis_cfg = container.settings.redis
        client = redis.from_url(str(redis_cfg.url), decode_responses=True)
        token = uuid.uuid4().hex
        key = f"{redis_cfg.prefix}lock:{name}"
        claimed = await client.set(key, token, ex=max(1, int(ttl_seconds)), nx=True)
        return client, key, token, bool(claimed)
    except Exception as exc:
        logger.warning("scheduler_lock_unavailable", extra={"context": {"name": name, "error": str(exc)}})
        return None, "", "", True


async def _release_redis_lock(client, key: str, token: str) -> None:
    if not client or not key or not token:
        return
    try:
        await client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
            1,
            key,
            token,
        )
    except Exception as exc:
        logger.warning("scheduler_lock_release_failed", extra={"context": {"key": key, "error": str(exc)}})
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


async def backup_scheduler(container) -> None:
    """Run automated system + user backups on schedule."""
    await asyncio.sleep(60)
    while True:
        try:
            enabled = container.db.get_setting(
                "backup.enabled", "true"
            ).lower() in ("true", "1", "yes", "on")

            if not enabled:
                await asyncio.sleep(3600)
                continue

            interval_hours = 6
            try:
                interval_hours = max(1, int(container.db.get_setting("backup.interval_hours", "6")))
            except (ValueError, TypeError):
                pass

            await asyncio.sleep(interval_hours * 3600)

            lock_client, lock_key, lock_token, claimed = await _claim_redis_lock(
                container,
                "backup-scheduler",
                ttl_seconds=max(3600, interval_hours * 3600),
            )
            if not claimed:
                continue
            try:
                full_result = container.backup_service.full_backup()
                if full_result.get("status") != "completed":
                    logger.warning("full_backup_failed", extra={"context": full_result})
                container.backup_service.create_system_backup()
                container.backup_service.create_user_backup()

                for category in ["full", "system", "users"]:
                    for target in ["rclone", "r2"]:
                        try:
                            container.backup_service.rclone_sync_latest_category(category, target=target)
                        except Exception as exc:
                            logger.warning("backup_rclone_skip: %s", exc)
                    try:
                        container.backup_service.telegram_sync_latest_category(category)
                    except Exception as exc:
                        logger.warning("backup_telegram_skip: %s", exc)
            finally:
                await _release_redis_lock(lock_client, lock_key, lock_token)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("backup_scheduler_failed", extra={"context": {"error": str(exc)}})
            await asyncio.sleep(3600)


async def subscription_expiry_loop(container) -> None:
    """Check for expired subscriptions every hour."""
    await asyncio.sleep(120)
    while True:
        try:
            lock_client, lock_key, lock_token, claimed = await _claim_redis_lock(
                container,
                "subscription-expiry",
                ttl_seconds=3300,
            )
            if not claimed:
                await asyncio.sleep(3600)
                continue
            try:
                from app.core.models import UserSubscription

                session = get_session()
                now_dt = datetime.now(timezone.utc)
                three_days = now_dt + timedelta(days=3)
                soon = (
                    session.query(UserSubscription)
                    .filter(
                        UserSubscription.status == "active",
                        UserSubscription.end_at.between(now_dt, three_days),
                    )
                    .all()
                )
                if soon:
                    logger.info("subscriptions_expiring_soon: %s", len(soon))
                session.close()
            except Exception as exc:
                logger.warning("expiry_warning_failed: %s", exc)

            expired_users = container.subscription_service.expire_overdue()
            if expired_users:
                logger.info("auto_expired: %s subscriptions", len(expired_users))
            await _release_redis_lock(lock_client, lock_key, lock_token)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("expiry_check_failed: %s", exc)
            try:
                await _release_redis_lock(lock_client, lock_key, lock_token)
            except Exception:
                pass
        await asyncio.sleep(3600)
