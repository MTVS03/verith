"""stock_aliases seed 정의 (backend 단일 정본).

**공식 이름은 여기 넣지 않는다** — 공식 이름 정본은 `stocks.stock_name`이고, resolver 는 거기서
매칭한다(match_type=stock_name). 이 목록에는 **변형 alias 만** 둔다(한글 변형/영문/약칭/구명/모호그룹).

alias_type:
- korean_variant / english / abbreviation / former_name : 특정 1종목 지칭
- ambiguous_group : 여러 종목이 공유하는 모호 표현(절대 단일 자동확정 금지) — 명시적으로 각 종목에 연결
normalized_alias 는 seed 시 `normalize_stock_text` 로 생성한다(직접 작성 금지).
"""

from __future__ import annotations

# {stock_code, alias, alias_type}. stock_code 는 문자열.
ALIAS_SEED: list[dict[str, str]] = [
    # 051910 LG화학
    {"stock_code": "051910", "alias": "엘지화학", "alias_type": "korean_variant"},
    {"stock_code": "051910", "alias": "LG Chem", "alias_type": "english"},
    # 373220 LG에너지솔루션
    {"stock_code": "373220", "alias": "엘지에너지솔루션", "alias_type": "korean_variant"},
    {"stock_code": "373220", "alias": "LG Energy Solution", "alias_type": "english"},
    {"stock_code": "373220", "alias": "엘지엔솔", "alias_type": "abbreviation"},
    {"stock_code": "373220", "alias": "LGES", "alias_type": "abbreviation"},
    # 006400 삼성SDI
    {"stock_code": "006400", "alias": "삼성에스디아이", "alias_type": "korean_variant"},
    {"stock_code": "006400", "alias": "Samsung SDI", "alias_type": "english"},
    # 096770 SK이노베이션
    {"stock_code": "096770", "alias": "에스케이이노베이션", "alias_type": "korean_variant"},
    {"stock_code": "096770", "alias": "SK Innovation", "alias_type": "english"},
    # 086520 에코프로
    {"stock_code": "086520", "alias": "Ecopro", "alias_type": "english"},
    # 247540 에코프로비엠
    {"stock_code": "247540", "alias": "Ecopro BM", "alias_type": "english"},
    {"stock_code": "247540", "alias": "에코프로BM", "alias_type": "korean_variant"},
    # 003670 포스코퓨처엠
    {"stock_code": "003670", "alias": "포스코케미칼", "alias_type": "former_name"},
    {"stock_code": "003670", "alias": "POSCO Future M", "alias_type": "english"},
    {"stock_code": "003670", "alias": "포퓨", "alias_type": "abbreviation"},
    # 066970 엘앤에프
    {"stock_code": "066970", "alias": "엘엔에프", "alias_type": "korean_variant"},
    {"stock_code": "066970", "alias": "L&F", "alias_type": "english"},
    # 348370 엔켐
    {"stock_code": "348370", "alias": "Enchem", "alias_type": "english"},
    # 361610 SK아이이테크놀로지
    {"stock_code": "361610", "alias": "에스케이아이이테크놀로지", "alias_type": "korean_variant"},
    {"stock_code": "361610", "alias": "SK IET", "alias_type": "english"},
    {"stock_code": "361610", "alias": "SKIET", "alias_type": "abbreviation"},
    # ── ambiguous_group (여러 종목 공유, 각 종목에 명시 연결) ──────────────────
    {"stock_code": "051910", "alias": "LG", "alias_type": "ambiguous_group"},
    {"stock_code": "373220", "alias": "LG", "alias_type": "ambiguous_group"},
    {"stock_code": "096770", "alias": "SK", "alias_type": "ambiguous_group"},
    {"stock_code": "361610", "alias": "SK", "alias_type": "ambiguous_group"},
    {"stock_code": "086520", "alias": "에코", "alias_type": "ambiguous_group"},
    {"stock_code": "247540", "alias": "에코", "alias_type": "ambiguous_group"},
]


# 대표 확장 종목 별칭(변형만). `constants/stocks.REPRESENTATIVE_STOCKS` 와 짝이며, battery `ALIAS_SEED`
# 와 **분리**된 목록이다(공식명은 여기 넣지 않는다 — 정본은 stocks.stock_name).
# `scripts/seed_representative_stocks.py` 가 이 목록을 읽어 seed 한다.
REPRESENTATIVE_ALIAS_SEED: list[dict[str, str]] = [
    # 005930 삼성전자
    {"stock_code": "005930", "alias": "삼전", "alias_type": "abbreviation"},
    {"stock_code": "005930", "alias": "Samsung Electronics", "alias_type": "english"},
    # 005935 삼성전자우
    {"stock_code": "005935", "alias": "삼성전자우선주", "alias_type": "korean_variant"},
    # 035720 카카오
    {"stock_code": "035720", "alias": "Kakao", "alias_type": "english"},
    {"stock_code": "035720", "alias": "다음카카오", "alias_type": "former_name"},
]
