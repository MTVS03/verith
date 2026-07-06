"""KIS 토큰 파일 캐시 — 네트워크 없이 캐시 로직만 검증.

원리: 캐시의 가치는 "유효하면 발급 안 함, 만료면 발급"이라는 분기다.
  헬퍼(_read_cache/_write_cache)는 tmp_path 로 왕복·만료·손상을 검증하고,
  _get_token 은 발급 함수를 가짜로 바꿔 '캐시가 있으면 발급 0회'를 확인한다.
  실제 KIS 호출은 없다(과금·네트워크·403 무관).
"""

import sys
import time
from pathlib import Path

# 네임스페이스 패키지(PEP 420) — src 를 경로에 넣어 agents.flow.* 를 import.
_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agents.flow.core import kis_client  # noqa: E402


def test_cache_roundtrip(tmp_path):
    """저장한 토큰이 만료 전이면 그대로 읽힌다."""
    p = tmp_path / "tok.json"
    kis_client._write_cache(p, "tok-abc", expires_at=1000.0)
    assert kis_client._read_cache(p, now=100.0) == "tok-abc"


def test_expired_or_margin_cache_returns_none(tmp_path):
    """만료됐거나 만료 60초 이내(마진)면 캐시를 쓰지 않는다."""
    p = tmp_path / "tok.json"
    kis_client._write_cache(p, "tok-abc", expires_at=1000.0)
    assert kis_client._read_cache(p, now=2000.0) is None      # 완전 만료
    assert kis_client._read_cache(p, now=950.0) is None       # 마진(60초) 안


def test_missing_or_broken_cache_returns_none(tmp_path):
    """파일 없음·JSON 손상·필드 누락 전부 None — 조용히 발급 경로로 후퇴."""
    assert kis_client._read_cache(tmp_path / "none.json", now=0.0) is None
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert kis_client._read_cache(bad, now=0.0) is None
    nofield = tmp_path / "nofield.json"
    nofield.write_text("{}", encoding="utf-8")
    assert kis_client._read_cache(nofield, now=0.0) is None


def test_valid_cache_skips_issuance(monkeypatch, tmp_path):
    """유효 캐시가 있으면 발급을 아예 부르지 않는다(빈도 제한 회피의 핵심)."""
    p = tmp_path / "tok.json"
    kis_client._write_cache(p, "tok-cached", expires_at=time.time() + 3600)
    monkeypatch.setattr(kis_client, "_TOKEN_CACHE_PATH", p)

    def boom(client, key, secret):
        raise AssertionError("유효 캐시가 있는데 발급이 호출됨")

    monkeypatch.setattr(kis_client, "_issue_token", boom)
    assert kis_client._get_token(None, "k", "s") == "tok-cached"


def test_expired_cache_triggers_issuance_and_refreshes(monkeypatch, tmp_path):
    """만료 캐시면 발급하고, 새 토큰이 캐시에 다시 저장된다."""
    p = tmp_path / "tok.json"
    kis_client._write_cache(p, "tok-old", expires_at=time.time() - 10)
    monkeypatch.setattr(kis_client, "_TOKEN_CACHE_PATH", p)
    monkeypatch.setattr(
        kis_client, "_issue_token", lambda client, key, secret: ("tok-new", 86400.0)
    )
    assert kis_client._get_token(None, "k", "s") == "tok-new"
    assert kis_client._read_cache(p, now=time.time()) == "tok-new"   # 캐시 갱신 확인
