"""Small synchronous adapter boundary, shared by the engine and built-in sources."""
from dataclasses import dataclass, field
from typing import Protocol
import math
from ..limits import MAX_RETRY_SECONDS, NOT_FOUND_RETRY_SECONDS


class SourceError(Exception):
    """Public, sanitized failure. Never put URLs, credentials or response bodies here."""
    def __init__(self, message, status=0, retry_after=600):
        super().__init__(message)
        self.status = status
        cap = NOT_FOUND_RETRY_SECONDS if status == 404 else MAX_RETRY_SECONDS
        try:
            delay = float(retry_after)
        except (ValueError, TypeError, OverflowError):
            delay = 600
        self.retry_after = min(cap, max(2, delay)) if math.isfinite(delay) else 600


class Deferred(SourceError):
    """Local reservation delay: never increments remote failures/backoff."""


@dataclass
class SourceResult:
    # None means an auxiliary refresh: retain the existing primary sample.
    sample: dict | None = None
    state: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    next_due: float | None = None


class SourceAdapter(Protocol):
    def poll(self, definition: dict, previous: dict | None, state: dict, *,
             now: float, net) -> SourceResult: ...

    def current(self, sample: dict, state: dict, *, now: float) -> dict:
        """Optional: decorate a copy with freshness-sensitive auxiliary metrics."""
        ...
