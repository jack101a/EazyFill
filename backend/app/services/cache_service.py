"""Simple in-memory result cache with TTL."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any


class CacheService:
    """TTL cache for duplicate solve requests."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

        # Start background cleanup thread
        self._cleanup_thread = threading.Thread(target=self._periodic_cleanup, daemon=True)
        self._cleanup_thread.start()

    def _periodic_cleanup(self) -> None:
        """Background loop to evict expired entries."""
        while True:
            time.sleep(self._ttl)
            self.cleanup()

    def cleanup(self) -> None:
        """Remove all expired entries from the cache."""
        now = time.time()
        with self._lock:
            expired = [k for k, (exp, _) in self._store.items() if now > exp]
            for k in expired:
                self._store.pop(k, None)

    def _key(
        self,
        task_type: str,
        payload_base64: str,
        domain: str | None = None,
        field_name: str | None = None,
    ) -> str:
        raw = f"{task_type}:{domain or ''}:{field_name or ''}:{payload_base64}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def get(
        self,
        task_type: str,
        payload_base64: str,
        domain: str | None = None,
        field_name: str | None = None,
    ) -> dict[str, Any] | None:
        """Return cached result if not expired."""

        key = self._key(task_type, payload_base64, domain=domain, field_name=field_name)
        with self._lock:
            if key not in self._store:
                return None
            expires_at, data = self._store[key]
            if time.time() > expires_at:
                del self._store[key]
                return None
            return data

    def set(
        self,
        task_type: str,
        payload_base64: str,
        value: dict[str, Any],
        domain: str | None = None,
        field_name: str | None = None,
    ) -> None:
        """Store cache value with TTL."""

        key = self._key(task_type, payload_base64, domain=domain, field_name=field_name)
        with self._lock:
            self._store[key] = (time.time() + self._ttl, value)
