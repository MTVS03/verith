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
# 실데이터 검산(sync_stocks --inspect)으로 확정: 공식 field_specs 누적합(228/222)은 실제보다 1 크다
# (tail 창이 한글명 끝 공백 1문자를 물어 group='ST'가 ' S'로 밀렸음). tail_len 을 -1 하면 tail[0] 이
# 'ST' 로 맞고 group/etp/spac/pref 가 상대 오프셋이라 일괄 정렬된다. KOSPI 005930·KOSDAQ 086520 검산.
KOSPI_TAIL = 227
KOSDAQ_TAIL = 221

# ── tail 내부 필드 (name → (offset, width)) ─────────────────────────────────
# tail 내부 오프셋(tail[0] 기준). 실데이터 검산으로 확정(005930·005935·069500 앵커 diff).
KOSPI_FIELDS: dict[str, tuple[int, int]] = {
    "group": (0, 2),     # 증권그룹구분코드 (ST/EF/RT/BC/… — 005930='ST')
    "etp": (35, 1),      # ETP 상품구분(ETF=Y, 주권=N — 069500=Y, 005930=N). ETF/ETN은 group으로 이미 제외되는 이중장치
    "spac": (29, 1),     # SPAC 여부(보조 제외). KOSPI SPAC 앵커 부재로 값 미검증 — fail-open(false 제외 0)
    "pref": (158, 1),    # 우선주 구분(005935=set, 005930=미set). is_preferred 통계용(저장 안 함)
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

# ── 값 의미(value semantics) 상태 ───────────────────────────────────────────
# **실데이터 검산 완료(True)**: `sync_stocks --inspect` 로 앵커 검산해 offset/값 의미를 확정했다.
#   - 검증됨: group='ST'(주권; 005930·005935·086520·247540), ETF='EF'/REIT='RT'(group 제외),
#     KOSPI etp(35)=ETF만 Y·주권 N(069500 Y, 005930 N), KOSPI 우선주(158)=005935 set·005930 미set,
#     KOSDAQ spac(24)=실 SPAC(디비금융제N호스팩) 검출(43건).
#   - fail-open(값 미검증이나 false 제외 0): KOSPI spac(SPAC 앵커 부재)·KOSDAQ etp/pref(앵커 부재).
#     ETF/ETN/REIT 는 group 으로 이미 제외되므로 이 보조 필터가 틀려도 실제 주권을 배제하지 않는다.
FLAG_VALUE_SEMANTICS_VERIFIED = True

# 증권그룹구분코드 — 주권 값(KIS 표준 추정). 1차 포함 판정의 근거. 보통주·우선주 모두 이 값.
GROUP_CODE_STOCK = "ST"  # 검산 전 추정

# 플래그 설정으로 볼 값(검산 전 추정). 안전을 위해 **fail-open**: 추정이 틀려도 실제 주권을 배제하지
# 않고(포함 1차 판정은 그룹코드==ST), 최악의 경우 SPAC/ETP 일부가 유입될 뿐이다. SPAC/ETP 는 보조 제외.
_FLAG_SET_VALUES_PROVISIONAL = frozenset({"Y", "1"})


def spac_flag_set(value: str) -> bool:
    """기업인수목적회사여부 플래그가 설정됐는지(**추정값 기준**, 보조 제외용). 공백/N/0 은 미설정."""
    return value.strip().upper() in _FLAG_SET_VALUES_PROVISIONAL


def etp_flag_set(value: str) -> bool:
    """ETP 상품구분 플래그가 설정됐는지(**추정값 기준**). ETF/ETN 은 그룹코드로 이미 제외되므로 이중 안전장치."""
    return value.strip().upper() in _FLAG_SET_VALUES_PROVISIONAL
