# utils/html_parser.py
"""본문 HTML → 태그 제거된 순수 텍스트 추출. 순수 함수(네트워크 호출 없음).

Article.content는 원시 HTML이 아니라 순수 텍스트여야 한다(임베딩·요약 품질/저장 용량,
TASK 01 §3.1). script/style/nav/광고 등 본문이 아닌 노이즈를 최대한 제거하고, 최소한
태그·공백 정리는 보장한다. 크롤러(services/crawler.py)가 받아온 HTML을 이 함수로 정제한다.
표준 라이브러리(html.parser)만 사용.
"""
from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

# 통째로 버리는 영역(본문 아님). 여는 태그~닫는 태그 사이 텍스트를 수집하지 않는다.
_SKIP_TAGS = {
    "script", "style", "noscript", "template", "head", "title",
    "nav", "aside", "header", "footer", "form", "svg", "iframe",
}
# 텍스트 흐름을 끊는 블록 태그. 앞뒤에 개행을 넣어 단어가 붙지 않게 한다.
_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
}

_INLINE_WS = re.compile(r"[ \t\r\f\v ]+")


class _TextExtractor(HTMLParser):
    """SKIP 영역을 제외한 텍스트만 모으는 파서. 블록 경계엔 개행을 넣는다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        # <br/> 같은 self-closing 블록 태그도 개행 처리.
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def extract_text(html: str) -> str:
    """기사 HTML → 태그 제거된 순수 텍스트 본문.

    script/style/nav/광고 영역 제거, 공백·개행 정리. 원시 HTML은 반환하지 않는다.
    파싱이 부분 실패해도 수집된 만큼은 정제해 돌려준다(예외로 죽이지 않음).
    """
    if not html:
        return ""

    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # 깨진 HTML도 수집분은 살린다
        logger.debug("HTML 파싱 부분 실패(수집분 사용): %s", exc)

    raw = parser.text()
    # 줄 단위로 인라인 공백을 하나로, 빈 줄 제거.
    lines = (_INLINE_WS.sub(" ", line).strip() for line in raw.split("\n"))
    return "\n".join(line for line in lines if line)
