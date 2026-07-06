from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class CircuitBreakerState:
    failures: int = 0
    skip_until: float = 0.0


async def run_async_step(operation: Callable[[], Awaitable[T]]) -> T:
    return await operation()
