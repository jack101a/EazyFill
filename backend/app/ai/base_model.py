"""AI model interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseAIModel(ABC):
    """Abstract model for pluggable AI processors."""

    @abstractmethod
    async def solve(self, task_type: str, payload_base64: str) -> str:
        """Process task and return result string."""
