from __future__ import annotations

import pytest
import psycopg

from src.agents.fundamental.data import corp_code


def test_corp_code_falls_back_to_static_map_when_db_is_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(corp_code.settings, "VERITH_DB_URL", "")
    corp_code.clear_resolution_cache()

    result = corp_code.resolve_details("051910")

    assert result.corp_code == "00356361"
    assert result.source == "static_fallback"
    assert corp_code.CORP_CODE_FALLBACK_STATIC_FLAG in result.risk_flags
    assert corp_code.resolve("051910") == "00356361"


def test_corp_code_uses_backend_resolution_when_available(monkeypatch) -> None:
    corp_code.clear_resolution_cache()

    def fake_lookup(stock_code: str) -> corp_code.CorpCodeResolution:
        return corp_code.CorpCodeResolution(
            stock_code=stock_code,
            corp_code="00126380",
            corp_name="삼성전자",
            source="backend_stock_corp_codes",
        )

    monkeypatch.setattr(corp_code, "_lookup_backend_with_retry", fake_lookup)

    result = corp_code.resolve_details("005930")

    assert result.corp_code == "00126380"
    assert result.corp_name == "삼성전자"
    assert result.source == "backend_stock_corp_codes"
    assert result.risk_flags == ()


def test_corp_code_falls_back_when_backend_query_fails(monkeypatch) -> None:
    corp_code.clear_resolution_cache()

    def fake_lookup(_stock_code: str) -> None:
        raise corp_code.CorpCodeRepositoryQueryError("OperationalError")

    monkeypatch.setattr(corp_code, "_lookup_backend_with_retry", fake_lookup)

    result = corp_code.resolve_details("006400")

    assert result.corp_code == "00126362"
    assert result.source == "static_fallback"
    assert result.risk_flags == (corp_code.CORP_CODE_FALLBACK_STATIC_FLAG,)


def test_corp_code_unknown_stock_remains_explicit_error(monkeypatch) -> None:
    monkeypatch.setattr(corp_code.settings, "VERITH_DB_URL", "")
    corp_code.clear_resolution_cache()

    with pytest.raises(corp_code.UnknownStockCodeError):
        corp_code.resolve_details("000000")


@pytest.mark.parametrize(
    ("db_url", "expected"),
    [
        ("postgresql+asyncpg://user:pw@localhost:5433/verith", "postgresql://user:pw@localhost:5433/verith"),
        ("postgres+asyncpg://user:pw@localhost:5433/verith", "postgres://user:pw@localhost:5433/verith"),
        ("postgresql://user:pw@localhost:5433/verith", "postgresql://user:pw@localhost:5433/verith"),
    ],
)
def test_normalize_db_url(db_url: str, expected: str) -> None:
    assert corp_code._normalize_db_url(db_url) == expected


class _FakeCursor:
    def __init__(self, row: dict[str, str] | None) -> None:
        self.row = row
        self.executed: tuple[str, tuple[str, ...]] | None = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[str, ...]) -> None:
        self.executed = (query, params)

    def fetchone(self) -> dict[str, str] | None:
        return self.row


class _FakeConnection:
    def __init__(self, row: dict[str, str] | None) -> None:
        self.cursor_obj = _FakeCursor(row)

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj


def test_backend_lookup_maps_row_to_resolution(monkeypatch) -> None:
    monkeypatch.setattr(corp_code.settings, "VERITH_DB_URL", "postgresql+asyncpg://user:pw@localhost:5433/verith")
    connection = _FakeConnection(
        {
            "stock_code": "005930",
            "corp_code": "00126380",
            "corp_name_from_dart": "삼성전자",
        }
    )

    def fake_connect(*_args: object, **_kwargs: object) -> _FakeConnection:
        return connection

    monkeypatch.setattr(psycopg, "connect", fake_connect)

    result = corp_code._backend_lookup("005930")

    assert result == corp_code.CorpCodeResolution(
        stock_code="005930",
        corp_code="00126380",
        corp_name="삼성전자",
        source="backend_stock_corp_codes",
    )
    assert connection.cursor_obj.executed is not None
    assert connection.cursor_obj.executed[1] == ("005930",)


def test_backend_lookup_returns_none_when_row_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(corp_code.settings, "VERITH_DB_URL", "postgresql://user:pw@localhost:5433/verith")
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: _FakeConnection(None))

    assert corp_code._backend_lookup("000000") is None


def test_backend_lookup_wraps_psycopg_error(monkeypatch) -> None:
    monkeypatch.setattr(corp_code.settings, "VERITH_DB_URL", "postgresql://user:pw@localhost:5433/verith")

    def fake_connect(*_args: object, **_kwargs: object) -> None:
        raise psycopg.OperationalError("connection failed")

    monkeypatch.setattr(psycopg, "connect", fake_connect)

    with pytest.raises(corp_code.CorpCodeRepositoryQueryError):
        corp_code._backend_lookup("005930")
