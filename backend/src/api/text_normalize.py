"""종목 텍스트 정규화 (resolver + alias seed 공용).

규칙(확정): NFKC → casefold → 앞뒤 공백 제거 → 한글·영문·숫자 외 문자 제거 → 빈 문자열이면 거부.
seed 의 normalized_alias 와 resolver 의 질의 정규화는 반드시 이 함수 하나로 생성한다.
"""

from __future__ import annotations

import re
import unicodedata

# casefold 후: 숫자, 소문자 라틴, 한글 음절만 남긴다(공백·구두점·기타 제거).
_DISALLOWED = re.compile(r"[^0-9a-z가-힣]")


def normalize_stock_text(value: str) -> str:
    """정규화 문자열 반환. 결과가 빈 문자열일 수 있으므로 호출부에서 빈 값을 검증한다."""
    s = unicodedata.normalize("NFKC", value)
    s = s.casefold().strip()
    return _DISALLOWED.sub("", s)
