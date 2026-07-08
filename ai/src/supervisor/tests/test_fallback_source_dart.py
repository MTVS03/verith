"""DART 스냅샷 fallback source 테스트 — 결정론, 실 네트워크·DB 없음.

DART 공시명 exact 조회, miss, 스냅샷 부재/손상 → FallbackLookupError, composite 결합(curated+DART).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from src.supervisor.planning.fallback_lookup import FallbackLookupError
from src.supervisor.planning.fallback_source import (
    CURATED_FALLBACK_ENTRIES,
    CompositeFallbackLookup,
    CuratedFallbackSource,
    FallbackEntry,
)
from src.supervisor.planning.fallback_source_dart import DartSnapshotFallbackSource

_SNAPSHOT = pathlib.Path(__file__).parents[1] / "planning" / "data" / "dart_corp_snapshot.json"


def _dart() -> DartSnapshotFallbackSource:
    return DartSnapshotFallbackSource()


# ── DART source 단위 ────────────────────────────────────────────────────────
def test_dart_snapshot_file_exists_and_shaped():
    doc = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    assert isinstance(doc["entries"], list) and doc["entries"]
    for e in doc["entries"][:5]:
        assert len(e["stock_code"]) == 6 and e["stock_code"].isdigit()
        assert e["corp_name"] and e["stock_name"]


def test_dart_corp_name_exact_resolves_via_composite():
    r = CompositeFallbackLookup([_dart()]).lookup("삼성화재해상보험 실적 어때")
    assert r.status == "resolved" and r.stock.stock_code == "000810"
    assert r.stock.stock_name == "삼성화재"          # 표시명은 canonical stock_name
    assert r.meta.final_source == "dart"


def test_dart_source_hit_is_name_exact():
    hits = _dart().find("케이씨씨 분석")
    assert any(h.stock_code == "002380" and h.match == "name_exact" and h.source == "dart" for h in hits)


def test_dart_miss_is_not_found():
    assert CompositeFallbackLookup([_dart()]).lookup("전혀없는회사이름xyz").status == "not_found"


def test_dart_missing_snapshot_raises_fallback_error():
    src = DartSnapshotFallbackSource(path=pathlib.Path("/no/such/dart_snapshot.json"))
    with pytest.raises(FallbackLookupError):
        src.find("삼성화재해상보험")


def test_dart_corrupt_snapshot_raises_fallback_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(FallbackLookupError):
        DartSnapshotFallbackSource(path=bad).find("아무거나")


def test_dart_snapshot_no_entries_key_raises(tmp_path):
    bad = tmp_path / "noentries.json"
    bad.write_text(json.dumps({"foo": []}), encoding="utf-8")
    with pytest.raises(FallbackLookupError):
        DartSnapshotFallbackSource(path=bad).find("아무거나")


# ── composite: curated + DART 결합 ──────────────────────────────────────────
def test_composite_curated_plus_dart_distinct_codes_ambiguous():
    # curated(Samsung Electronics→005930) + DART(삼성화재해상보험→000810) 둘 다 hit → ambiguous.
    comp = CompositeFallbackLookup(
        [CuratedFallbackSource(CURATED_FALLBACK_ENTRIES), _dart()]
    )
    r = comp.lookup("Samsung Electronics 그리고 삼성화재해상보험 비교")
    assert r.status == "ambiguous"
    assert {c.stock_code for c in r.candidates} == {"005930", "000810"}
    assert set(r.meta.source_hits) == {"curated", "dart"}


def test_composite_same_code_from_curated_and_dart_dedups():
    # curated 와 DART 가 같은 stock_code 를 가리키면 dedup → 단일 resolved.
    curated = CuratedFallbackSource((FallbackEntry("000810", "삼성화재", "KOSPI", ("Samsung F&M",)),))
    comp = CompositeFallbackLookup([curated, _dart()])
    r = comp.lookup("삼성화재해상보험 Samsung F&M")
    assert r.status == "resolved" and r.stock.stock_code == "000810"
    assert set(r.meta.source_hits) == {"curated", "dart"}   # 둘 다 hit 했지만 dedup


def test_lazy_load_no_io_at_construction(tmp_path):
    # 생성 시엔 파일을 읽지 않는다(잘못된 경로여도 construction 은 성공, find 때만 실패).
    src = DartSnapshotFallbackSource(path=tmp_path / "later.json")
    # 아직 로드 안 함 — 첫 find 에서만 시도.
    with pytest.raises(FallbackLookupError):
        src.find("x")
