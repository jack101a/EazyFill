from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.database import Database

class BaseRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @property
    def _lock(self):
        return self.db._lock

    def connect(self):
        return self.db.connect()

    def _normalize_domain(self, domain: str | None) -> str:
        return self.db._normalize_domain(domain)

    def _domain_candidates(self, domain: str | None) -> list[str]:
        return self.db._domain_candidates(domain)
