# utils/rss_parser.py
"""RSS/Atom XML → 원시 기사 항목(dict) 파싱. 순수 함수(네트워크 호출 없음).

- 입력→출력 순수 함수라 저장된 XML 픽스처로 테스트한다.
- 언론사마다 다른 날짜 포맷(RFC822/ISO8601)을 datetime(aware, KST)으로 정규화한다.
- 필수 필드(title/link)가 없거나 깨진 항목은 건너뛴다(항목 단위 격리).
- RSS 2.0(<item>)과 Atom(<entry>)을 모두 다룬다. 표준 라이브러리(xml.etree)만 사용.
"""
from __future__ import annotations

import email.utils
import logging
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# 발행시각 정규화 기준 타임존. 7일 롤링 삭제(published_at)와 일관되게 KST로 통일한다.
KST = timezone(timedelta(hours=9))

# 항목 컨테이너 태그(local name). RSS는 item, Atom은 entry.
_ITEM_TAGS = {"item", "entry"}
# 발행시각 후보 태그. dc:date 포함. 먼저 나온 값을 채택.
_DATE_TAGS = {"pubdate", "published", "updated", "date"}
_DESC_TAGS = {"description", "summary"}


def parse_rss(xml: str | bytes, publisher: str) -> list[dict]:
    """RSS/Atom XML → 원시 기사 항목 리스트.

    각 항목: {"title": str, "link": str, "published_at": datetime | None,
             "publisher": str, "description": str | None}

    - title/link 없는 항목은 skip(로깅).
    - 날짜 포맷은 datetime(aware, KST)으로 정규화. 실패 시 None(예외로 파이프라인을 죽이지 않음).
    - XML 전체가 깨져 파싱 불가하면 빈 리스트를 반환한다(피드 단위 격리는 호출측 services/rss.py).
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        logger.warning("RSS XML 파싱 실패 (publisher=%s): %s", publisher, exc)
        return []

    items: list[dict] = []
    for el in root.iter():
        if _localname(el.tag) in _ITEM_TAGS:
            parsed = _parse_item(el, publisher)
            if parsed is not None:
                items.append(parsed)
    return items


def _parse_item(el: ET.Element, publisher: str) -> dict | None:
    """단일 <item>/<entry> → 항목 dict. 필수 필드 없으면 None."""
    title: str | None = None
    link: str | None = None
    published_raw: str | None = None
    description: str | None = None

    for child in el:
        tag = _localname(child.tag)
        if tag == "title" and title is None:
            title = (child.text or "").strip() or None
        elif tag == "link":
            link = link or _extract_link(child)
        elif tag in _DATE_TAGS and published_raw is None:
            published_raw = (child.text or "").strip() or None
        elif tag in _DESC_TAGS and description is None:
            description = (child.text or "").strip() or None

    if not title or not link:
        logger.debug("RSS 항목 skip: title/link 누락 (publisher=%s)", publisher)
        return None

    return {
        "title": title,
        "link": link,
        "published_at": _parse_date(published_raw),
        "publisher": publisher,
        "description": description,
    }


def _extract_link(child: ET.Element) -> str | None:
    """<link>: RSS는 텍스트, Atom은 href 속성. Atom은 rel=alternate(대표 링크)를 우선."""
    href = child.get("href")
    if href:
        rel = child.get("rel")
        if rel in (None, "", "alternate"):
            return href.strip() or None
        return None
    if child.text and child.text.strip():
        return child.text.strip()
    return None


def _parse_date(raw: str | None) -> datetime | None:
    """RFC822 또는 ISO8601 문자열 → datetime(aware, KST). 실패 시 None."""
    if not raw:
        return None
    # 1) RFC822 (예: "Mon, 06 Jul 2026 09:00:00 +0900")
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt is not None:
            return _to_kst(dt)
    except (TypeError, ValueError):
        pass
    # 2) ISO8601 (예: "2026-07-06T09:00:00+09:00" / "...Z")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return _to_kst(dt)
    except ValueError:
        pass
    logger.debug("발행시각 파싱 실패 → None: %r", raw)
    return None


def _to_kst(dt: datetime) -> datetime:
    """naive면 KST로 간주, aware면 KST로 변환. 항상 aware 반환."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def _localname(tag: str) -> str:
    """'{ns}tag' → 'tag'(소문자). 네임스페이스(Atom·dc 등) 무시."""
    if "}" in tag:
        tag = tag.rsplit("}", 1)[1]
    return tag.lower()
