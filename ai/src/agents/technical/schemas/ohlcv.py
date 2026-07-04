"""기술적 분석 에이전트 — 내부 표준 OHLCV 모델.

KIS 국내주식기간별시세 응답(`output2`)을 코드 전역에서 쓰는 내부 표준 구조로 바꾼 결과다.
KIS 원본 필드명(`stck_bsop_date` 등)은 `services/kis_client.py` 변환 경계까지만 존재하고,
그 이후 모듈(indicators·regime·charts)은 이 모델만 본다(technical_coding_guidelines §8.2).

정본: `docs/kis_mapping.md §7`(필드 매핑)·§11(실측). `date`는 ISO(`YYYY-MM-DD`)로 정규화한다.
이번 단계 범위: 순수 데이터 모델만. pandas DataFrame·지표 계산용 파생 컬럼은 만들지 않는다.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OHLCV(BaseModel):
    """한 봉(일/주/월)의 내부 표준 OHLCV. 계약에 없는 필드 유입 차단(extra=forbid).

    가격·거래량·거래대금은 음수가 될 수 없으므로 ge=0으로 제약한다(chart_data 계약에서
    candles로 그대로 재사용되며, 시세 값의 음수는 비정상 응답이다).
    """
    model_config = ConfigDict(extra="forbid")

    date: str  # ISO 형식 "YYYY-MM-DD" (KIS 원본 "YYYYMMDD"를 kis_client에서 정규화)
    open: int | float = Field(ge=0)
    high: int | float = Field(ge=0)
    low: int | float = Field(ge=0)
    close: int | float = Field(ge=0)
    volume: int = Field(ge=0)
    trading_value: int = Field(ge=0)  # KIS `acml_tr_pbmn`(누적 거래대금). 유동성 판정 근거값.
