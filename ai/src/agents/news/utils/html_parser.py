# utils/html_parser.py
"""본문 HTML → 태그 제거된 순수 텍스트 추출. 순수 함수(네트워크 호출 없음).

Article.content는 원시 HTML이 아니라 순수 텍스트여야 한다(임베딩·요약 품질/저장 용량,
TASK 01 §3.1). script/style/nav/광고 등 본문이 아닌 노이즈를 최대한 제거하고, 최소한
태그·공백 정리는 보장한다. 크롤러(services/crawler.py)가 받아온 HTML을 이 함수로 정제한다.
표준 라이브러리(html.parser)만 사용.
"""
from __future__ import annotations

import json
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

    일부 언론사는 본문을 <p>가 아니라 <script> 안 JSON(Arc XP/Fusion, schema.org ld+json)에
    싣는다. 그 경우 보이는 텍스트는 nav/보일러플레이트뿐이라 본문이 유실된다. 그래서 <script>에
    임베드된 본문을 별도로 복구해, '보이는 텍스트'와 '임베드 본문' 중 더 실한 쪽을 본문으로 채택한다.
    (일반 페이지는 임베드 본문이 비어 있어 기존 동작 그대로 보이는 텍스트를 쓴다.)
    """
    if not html:
        return ""

    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # 깨진 HTML도 수집분은 살린다
        logger.debug("HTML 파싱 부분 실패(수집분 사용): %s", exc)

    visible = _normalize(parser.text())
    embedded = _extract_embedded_body(html)
    # 임베드 본문(script JSON)이 보이는 텍스트보다 실하면 그것을 본문으로 채택(JSON-in-script 대응).
    if len(embedded) > len(visible):
        return embedded
    return visible


def _normalize(raw: str) -> str:
    """줄 단위로 인라인 공백을 하나로, 빈 줄 제거."""
    lines = (_INLINE_WS.sub(" ", line).strip() for line in raw.split("\n"))
    return "\n".join(line for line in lines if line)


# ---------------------------------------------------------------------------
# <script> 임베드 본문 복구 (Arc XP/Fusion·schema.org ld+json)
# extract_text가 <script>를 건너뛰기 때문에, JSON에 실린 본문은 여기서 따로 되살린다.
# 표준 라이브러리(json·re)만 사용. 새 의존성 없음.
# ---------------------------------------------------------------------------
_INLINE_TAG = re.compile(r"<[^>]+>")
_LDJSON_BLOCK = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _extract_embedded_body(html: str) -> str:
    """<script>에 임베드된 기사 본문을 복구. 없으면 빈 문자열."""
    body = _fusion_body(html)          # 1) Arc XP/Fusion (조선일보 등)
    if body:
        return body
    return _ldjson_body(html)          # 2) 범용 schema.org NewsArticle.articleBody


def _fusion_body(html: str) -> str:
    """Arc XP/Fusion: `Fusion.globalContent = {...}` 의 content_elements(text) 를 이어붙인다.

    중첩 JSON은 정규식으로 자르면 깨지므로 json.raw_decode 로 균형 잡힌 객체만 정확히 파싱한다.
    """
    idx = html.find("Fusion.globalContent")
    if idx == -1:
        return ""
    eq = html.find("=", idx)
    start = html.find("{", eq) if eq != -1 else -1
    if start == -1:
        return ""
    try:
        obj, _ = json.JSONDecoder().raw_decode(html, start)
    except json.JSONDecodeError:
        return ""
    if not isinstance(obj, dict):
        return ""
    parts: list[str] = []
    for el in obj.get("content_elements") or []:
        if isinstance(el, dict) and el.get("type") == "text":
            content = el.get("content")
            if isinstance(content, str) and content.strip():
                parts.append(content)
    return _normalize(_INLINE_TAG.sub("", "\n".join(parts)))


def _ldjson_body(html: str) -> str:
    """schema.org ld+json 블록들에서 articleBody 를 찾아 반환(여러 블록·@graph·리스트 대응)."""
    if "application/ld+json" not in html:
        return ""
    for match in _LDJSON_BLOCK.finditer(html):
        try:
            data = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        body = _find_article_body(data)
        if body:
            return _normalize(_INLINE_TAG.sub("", body))
    return ""


def _find_article_body(data) -> str | None:
    """ld+json 구조(dict/list/@graph)를 재귀 탐색해 첫 articleBody 문자열을 찾는다."""
    if isinstance(data, dict):
        body = data.get("articleBody")
        if isinstance(body, str) and body.strip():
            return body
        for value in data.values():
            found = _find_article_body(value)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_article_body(item)
            if found:
                return found
    return None
