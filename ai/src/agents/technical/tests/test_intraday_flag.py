"""config._env_bool / INTRADAY_FETCH_ENABLED env override 파서 테스트.

env 값 파싱 규칙만 확인한다(모듈 상수 INTRADAY_FETCH_ENABLED는 import 시 1회 계산되므로
런타임 재평가가 필요한 파싱 규칙은 _env_bool로 검증한다).
"""

from __future__ import annotations

import pytest

from src.agents.technical import config

_KEY = "INTRADAY_FETCH_ENABLED"


def test_unset_returns_default(monkeypatch):
    monkeypatch.delenv(_KEY, raising=False)
    assert config._env_bool(_KEY, default=False) is False
    assert config._env_bool(_KEY, default=True) is True  # default 전달 확인


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", " On ", "Yes"])
def test_true_values(monkeypatch, raw):
    monkeypatch.setenv(_KEY, raw)
    assert config._env_bool(_KEY, default=False) is True


@pytest.mark.parametrize("raw", ["0", "false", "FALSE", "no", "off", "", "  "])
def test_false_values(monkeypatch, raw):
    monkeypatch.setenv(_KEY, raw)
    assert config._env_bool(_KEY, default=False) is False


@pytest.mark.parametrize("raw", ["maybe", "2", "enabled", "y", "ㅇㅇ"])
def test_unknown_value_warns_and_false(monkeypatch, raw):
    monkeypatch.setenv(_KEY, raw)
    with pytest.warns(UserWarning):
        result = config._env_bool(_KEY, default=False)
    assert result is False  # 조용한 True 금지 — 운영 안전


def test_module_default_is_false():
    # 기본 개발/CI 환경(.env에 flag 미설정)에서는 반드시 False.
    assert config.INTRADAY_FETCH_ENABLED is False
