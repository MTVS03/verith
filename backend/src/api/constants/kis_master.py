"""KIS 종목마스터 파싱 상수 (공식 파서 근거).

근거: KIS 공식 GitHub `koreainvestment/open-trading-api` 의
`stocks_info/kis_kospi_code_mst.py` · `kis_kosdaq_code_mst.py` (및 헤더 .h).

레코드 = front + tail. cp949 디코드 후 **문자 기준**으로 자른다(tail 필드는 ASCII 1바이트=1문자).
  front = row[:len(row)-TAIL]   # 단축코드[0:9] · 표준코드[9:21] · 한글명[21:]
  tail  = row[-TAIL:]           # 고정폭 필드(시장별 개수·위치 상이)

**KOSPI/KOSDAQ 는 tail 길이·필드 위치가 다르다** → 시장별 field-spec 필수.
아래 (tail_offset, width) 는 공식 `field_specs` 폭 리스트의 누적합으로 계산한 값이다.
"""

from __future__ import annotations

# front 공통 offset
FRONT_CODE = (0, 9)   # 단축코드
FRONT_STD = (9, 21)   # 표준코드
FRONT_NAME_START = 21  # 한글명 = front[21:]

# ── tail 길이 ────────────────────────────────────────────────────────────────
KOSPI_TAIL = 228
KOSDAQ_TAIL = 222

# ── tail 내부 필드 (name → (offset, width)) ─────────────────────────────────
# KOSPI: 그룹코드 idx0, ETP idx12, SPAC idx19, 우선주 idx49
KOSPI_FIELDS: dict[str, tuple[int, int]] = {
    "group": (0, 2),     # 증권그룹구분코드
    "etp": (21, 1),      # ETP
    "spac": (29, 1),     # SPAC(기업인수목적회사여부)
    "pref": (105, 1),    # 우선주
}
# KOSDAQ: 증권그룹구분코드 idx0, ETP 상품구분코드 idx8, 기업인수목적회사여부 idx14, 우선주 구분 코드 idx48
KOSDAQ_FIELDS: dict[str, tuple[int, int]] = {
    "group": (0, 2),
    "etp": (18, 1),
    "spac": (24, 1),
    "pref": (152, 1),
}

# ── 시장 라벨 (stocks.market 저장값) ────────────────────────────────────────
MARKET_KOSPI = "KOSPI"
MARKET_KOSDAQ = "KOSDAQ"

# ── 증권그룹구분코드 (KIS 표준) ─────────────────────────────────────────────
# 포함 대상은 주권(ST)뿐 — 보통주·우선주 모두 ST. 그 외(EF/EN/RT/MF/…)는 제외.
GROUP_CODE_STOCK = "ST"  # 주권


def spac_flag_set(value: str) -> bool:
    """기업인수목적회사여부 플래그가 설정됐는지(Y/1). 공백/N/0 은 미설정."""
    return value.strip().upper() in {"Y", "1"}


def etp_flag_set(value: str) -> bool:
    """ETP 상품구분 플래그가 설정됐는지. ETF/ETN 이중 제외용."""
    return value.strip().upper() in {"Y", "1"}
