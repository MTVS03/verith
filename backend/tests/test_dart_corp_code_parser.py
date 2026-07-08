"""DART corpCode.xml 파서 단위 테스트 (fixture bytes, 네트워크 없음)."""

from __future__ import annotations

import pytest

from src.api.services.dart_corp_code_parser import (
    CorpCodeParseError,
    parse_corp_code,
)
from tests.fixtures.dart_corp_code import CORP_XML, EXPECTED, corp_xml


def test_parses_only_listed_rows():
    result = parse_corp_code(CORP_XML)
    got = {r.stock_code: (r.corp_code, r.corp_name_from_dart, r.modify_date) for r in result.records}
    assert got == EXPECTED                 # 비상장(빈 stock_code) 제외
    assert result.non_listed == 1


def test_empty_stock_code_excluded():
    xml = corp_xml([
        {"corp_code": "00000001", "corp_name": "비상장", "stock_code": "", "modify_date": "20230101"},
        {"corp_code": "00000002", "corp_name": "공백코드", "stock_code": "   ", "modify_date": "20230101"},
    ])
    result = parse_corp_code(xml)
    assert result.records == [] and result.non_listed == 2


def test_invalid_modify_date_becomes_null_and_counted():
    xml = corp_xml([
        {"corp_code": "00000001", "corp_name": "정상", "stock_code": "000001", "modify_date": "20230101"},
        {"corp_code": "00000002", "corp_name": "이상", "stock_code": "000002", "modify_date": "2023-01"},
        {"corp_code": "00000003", "corp_name": "빈날짜", "stock_code": "000003", "modify_date": ""},
    ])
    result = parse_corp_code(xml)
    by_code = {r.stock_code: r.modify_date for r in result.records}
    assert by_code == {"000001": "20230101", "000002": None, "000003": None}
    assert result.invalid_modify_date == 1  # 빈 값은 count 안 함(형식 이상만)


def test_leading_zero_stock_code_preserved():
    xml = corp_xml([
        {"corp_code": "00000001", "corp_name": "앞자리0", "stock_code": "005930", "modify_date": "20230101"},
    ])
    result = parse_corp_code(xml)
    assert result.records[0].stock_code == "005930"


def test_duplicate_stock_code_fail_fast():
    xml = corp_xml([
        {"corp_code": "00000001", "corp_name": "A", "stock_code": "000001", "modify_date": "20230101"},
        {"corp_code": "00000002", "corp_name": "B", "stock_code": "000001", "modify_date": "20230101"},
    ])
    with pytest.raises(CorpCodeParseError):
        parse_corp_code(xml)


def test_duplicate_corp_code_fail_fast():
    xml = corp_xml([
        {"corp_code": "00000001", "corp_name": "A", "stock_code": "000001", "modify_date": "20230101"},
        {"corp_code": "00000001", "corp_name": "B", "stock_code": "000002", "modify_date": "20230101"},
    ])
    with pytest.raises(CorpCodeParseError):
        parse_corp_code(xml)


def test_listed_row_missing_corp_code_fail_fast():
    xml = corp_xml([
        {"corp_code": "", "corp_name": "코드없음", "stock_code": "000001", "modify_date": "20230101"},
    ])
    with pytest.raises(CorpCodeParseError):
        parse_corp_code(xml)


def test_listed_row_missing_corp_name_fail_fast():
    xml = corp_xml([
        {"corp_code": "00000001", "corp_name": "", "stock_code": "000001", "modify_date": "20230101"},
    ])
    with pytest.raises(CorpCodeParseError):
        parse_corp_code(xml)


def test_malformed_xml_raises():
    with pytest.raises(CorpCodeParseError):
        parse_corp_code(b"<result><list><corp_code>oops")


def test_empty_result_yields_no_records():
    assert parse_corp_code(corp_xml([])).records == []
