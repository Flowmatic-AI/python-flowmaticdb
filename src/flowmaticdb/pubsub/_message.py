from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    """One delivered message.

    ``id`` is the outbox row id on the polling backend and ``None`` on the
    backends that carry no row -- nothing in the public API depends on it, so it
    is there for logging and for tests that need to assert on ordering."""

    channel: str
    payload: str
    id: int | None = None
