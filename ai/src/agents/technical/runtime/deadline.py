"""실행 시간 예산(cooperative deadline) — Technical Agent 전체 처리 시간을 계약(60초) 안으로 묶는다.

endpoint가 `Deadline.after(TECHNICAL_AGENT_TIMEOUT_SECONDS)`로 만들어 agent→supervisor로 전달하고,
supervisor는 주요 stage 시작 전에 `check(stage)`로 예산 초과를 조기 감지한다. OpenAI 어댑터는
`remaining_seconds()`로 per-call timeout을 남은 시간 이하로 줄인다.

**협조적(cooperative)** 이다: 실행 중인 sync 작업을 강제로 죽이지 못하고, 다음 check 지점에서 멈춘다.
응답 레벨 `asyncio.wait_for`(endpoint)와 함께 써야 응답 시간까지 바운딩된다.

secret-safe: 메시지에 stage 이름만 담는다 — raw query·prompt·시세를 넣지 않는다.
시각은 `time.monotonic()`(벽시계 점프·시간대 무관)로 잰다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


class DeadlineExceeded(RuntimeError):
    """실행 시간 예산 초과. stage 이름만 담는다(secret/원문 미포함)."""


@dataclass(frozen=True)
class Deadline:
    """monotonic 만료 시각. `after()`로 만들거나 테스트에서 직접 `expires_at`을 넣는다."""

    expires_at: float  # time.monotonic() 기준 만료 시각(초)

    @classmethod
    def after(cls, seconds: float) -> Deadline:
        """지금부터 `seconds` 뒤 만료하는 deadline."""
        return cls(time.monotonic() + seconds)

    def remaining_seconds(self) -> float:
        """남은 초(음수 가능)."""
        return self.expires_at - time.monotonic()

    def expired(self) -> bool:
        return self.remaining_seconds() <= 0.0

    def check(self, stage: str) -> None:
        """만료됐으면 `DeadlineExceeded`(stage 이름 포함, secret 없음)."""
        if self.expired():
            raise DeadlineExceeded(f"deadline exceeded before {stage}")


def check_deadline(deadline: Deadline | None, stage: str) -> None:
    """None이면 무시, 아니면 `deadline.check(stage)`. 호출부 분기 중복을 줄이는 헬퍼."""
    if deadline is not None:
        deadline.check(stage)
