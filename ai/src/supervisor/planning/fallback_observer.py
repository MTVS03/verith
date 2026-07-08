"""fallback lookup 관측(observability) — 운영에서 fallback 이 얼마나/어떻게 쓰이는지 남긴다.

fallback 이 시도될 때마다 structured event 1건을 남긴다. supervisor 에는 기존 trace 계층이 없어 fallback
전용 경량 event 로 분리했다(주입식 — resolver/adapters 와 같은 패턴).

**남기는 것:** 시도 여부·source 별 hit 수·최종 status·최종 source·후보 수·match type·query 길이/정규화 길이,
그리고 (resolved 일 때만, 승격 후보 수집용) `normalized_query`·`stock_code`·`stock_name`·`market`.
**절대 남기지 않는 것:** **raw query 원문**(공백/원형 그대로)·API key/secret·원문 payload. normalized_query 는
정책상 허용(원문 아님)이며 후보 수집에 필요하다. metrics 로깅(`LoggingFallbackObserver`)은 query 내용을
로그에 찍지 않는다(길이·코드만) — normalized_query 는 opt-in capture sink 만 소비한다.
"""

from __future__ import annotations

import json
import logging
import pathlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from src.supervisor.schemas import ResolutionStatus


@dataclass(frozen=True)
class FallbackEvent:
    """fallback 시도 1건의 관측 스냅샷. raw query 원문은 담지 않는다(길이/정규화만)."""

    attempted: bool                       # 이 요청에서 fallback 을 실제로 시도했는지(항상 True 로 emit)
    final_status: ResolutionStatus        # 최종 판정(resolved/ambiguous/not_found)
    final_source: str | None = None       # resolved 를 만든 source 이름(ambiguous/not_found 면 None)
    source_hits: dict[str, int] = field(default_factory=dict)  # source 이름 → hit 수
    match_types: list[str] = field(default_factory=list)       # code_exact/name_exact/alias_exact(distinct)
    candidate_count: int = 0              # ambiguous 후보 수
    query_len: int = 0                    # 원문 길이(내용 아님)
    query_norm_len: int = 0               # 정규화 길이(내용 아님)
    # 승격 후보 수집용(resolved 일 때만 채움). raw query 아님(normalized) — 정책 허용.
    normalized_query: str | None = None
    stock_code: str | None = None
    stock_name: str | None = None
    market: str | None = None


class FallbackObserver(Protocol):
    """fallback 관측 경계. 구현체는 event 를 로깅/집계한다(부작용 없음이 기본 계약)."""

    def record(self, event: FallbackEvent) -> None:
        ...


class NullFallbackObserver:
    """no-op 관측자(기본 안전값). 아무것도 남기지 않는다."""

    def record(self, event: FallbackEvent) -> None:  # noqa: D401 - 의도적 no-op
        return None


class LoggingFallbackObserver:
    """structured event 를 `logging` 으로 남기는 운영 기본 관측자(secret-safe, 대량 dump 아님)."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger("verith.supervisor.fallback")

    def record(self, event: FallbackEvent) -> None:
        # 한 줄 구조화 요약 — raw query/secret 없음. extra 로 필드 노출(집계 파이프라인이 파싱 가능).
        self._log.info(
            "fallback_lookup status=%s source=%s hits=%s",
            event.final_status,
            event.final_source,
            event.source_hits,
            extra={
                "fallback_attempted": event.attempted,
                "fallback_final_status": event.final_status,
                "fallback_final_source": event.final_source,
                "fallback_source_hits": event.source_hits,
                "fallback_match_types": event.match_types,
                "fallback_candidate_count": event.candidate_count,
                "fallback_query_len": event.query_len,
                "fallback_query_norm_len": event.query_norm_len,
            },
        )


class RecordingFallbackObserver:
    """테스트용 — event 를 메모리에 모은다."""

    def __init__(self) -> None:
        self.events: list[FallbackEvent] = []

    def record(self, event: FallbackEvent) -> None:
        self.events.append(event)


class JsonlPromotionCaptureSink:
    """**opt-in** 승격-후보 capture sink — resolved fallback event 를 JSONL 로 append(오프라인 집계 입력).

    기본 배선이 아니다(request path 는 기본 write-free). ops 가 명시적으로 켤 때만 쓴다(canonical write 아님 —
    별도 capture 파일). raw query 는 쓰지 않는다(normalized_query 만). seen_at 은 capture 시각을 여기서 stamp
    한다(planner 는 clockless). resolved 가 아닌 event 는 무시한다(후보 아님)."""

    def __init__(self, path: str | pathlib.Path) -> None:
        self._path = pathlib.Path(path)

    def record(self, event: FallbackEvent) -> None:
        if event.final_status != "resolved" or not event.stock_code:
            return
        line = {
            "normalized_query": event.normalized_query,
            "stock_code": event.stock_code,
            "stock_name": event.stock_name,
            "market": event.market,
            "final_source": event.final_source,
            "match_types": list(event.match_types),
            "final_status": event.final_status,
            "seen_at": datetime.now(UTC).isoformat(),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


class MultiFallbackObserver:
    """여러 observer 에 동시 기록(예: 운영 logging + opt-in capture). 하나가 실패해도 나머지에 영향 없음."""

    def __init__(self, observers: list[FallbackObserver]) -> None:
        self._observers = list(observers)

    def record(self, event: FallbackEvent) -> None:
        for obs in self._observers:
            obs.record(event)
