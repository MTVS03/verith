"""DART 기반 fallback source — 정적 스냅샷(read-only) 조회. 네트워크·DB import 없음.

canonical resolver(stocks.stock_name + alias)가 못 잡는 **DART 공시명 표기**를 이번 요청에 한해 보조로
찾는다(예: "삼성화재해상보험"→005930·삼성화재, "케이씨씨"→002380·KCC). 스냅샷은 backend
`stock_corp_codes.corp_name_from_dart` 를 canonical(stocks)과 조인해 **정규화 후 stock_name 과 다른(additive)**
항목만 담은 read-only 데이터 아티팩트다(생성 provenance 는 json `_provenance`).

경계: 이 source 는 **조회만** 한다 — DART API 를 부르지도, canonical DB 를 write 하지도 않는다. ticker 를
생성하지 않고 이미 존재하는 정본 mapping(공시명→종목코드)을 exact 로 조회할 뿐이다. 스냅샷 갱신은 이
계층이 아니라 별도 승인형 관리 플로우의 몫이다. 파일 부재/손상은 `FallbackLookupError` 로 올린다(planner 가
not_found 로 흡수).

매칭: `fallback_source._matches`(latin 단어경계 + 한글 정규화 substring) 재사용. 스냅샷은 정규화 길이 ≥ 3
항목만 담아 짧은 이름 substring 오탐을 줄였다. fuzzy·edit-distance·semantic 은 없다.
"""

from __future__ import annotations

import json
import pathlib

from src.supervisor.planning.fallback_lookup import FallbackLookupError
from src.supervisor.planning.fallback_source import SourceHit, _matches, _tokens

_SNAPSHOT_PATH = pathlib.Path(__file__).with_name("data") / "dart_corp_snapshot.json"


class DartSnapshotFallbackSource:
    """DART 공시명 정적 스냅샷 조회 source(read-only). find(query) → corp_name exact hit."""

    def __init__(self, path: pathlib.Path | None = None, *, name: str = "dart") -> None:
        self.name = name
        self._path = path or _SNAPSHOT_PATH
        self._entries: list[dict] | None = None   # lazy load 캐시

    def _load(self) -> list[dict]:
        if self._entries is not None:
            return self._entries
        try:
            doc = json.loads(self._path.read_text(encoding="utf-8"))
            entries = doc["entries"]
            if not isinstance(entries, list):
                raise ValueError("entries 가 list 가 아님")
        except (OSError, ValueError, KeyError) as exc:
            # 스냅샷 부재/손상은 도구 장애로 분리 — canonical not_found 를 오염시키지 않는다.
            raise FallbackLookupError(f"DART 스냅샷 로드 실패: {type(exc).__name__}") from exc
        self._entries = entries
        return entries

    def find(self, query: str) -> list[SourceHit]:
        q_tokens = _tokens(query)
        q_norm = "".join(q_tokens)
        hits: list[SourceHit] = []
        for e in self._load():
            corp = e.get("corp_name")
            code = e.get("stock_code")
            if not corp or not code:
                continue
            if _matches(corp, q_tokens, q_norm):
                # 표시명은 canonical stock_name 을 우선(공시명은 매칭 키로만 사용).
                hits.append(
                    SourceHit(
                        stock_code=code,
                        stock_name=e.get("stock_name") or corp,
                        market=e.get("market"),
                        match="name_exact",
                        source=self.name,
                    )
                )
        return hits
