# tests/test_html_parser.py
"""utils/html_parser.extract_text 테스트 — 특히 <script> 임베드 본문 복구.

일반 페이지(<p> 본문)는 기존대로 보이는 텍스트를 쓰고, 본문을 <script> JSON 에 싣는
사이트(Arc XP/Fusion, schema.org ld+json)는 그 JSON 에서 본문을 되살리는지 확인한다.
네트워크 없이 문자열 픽스처로만 검증(순수 함수).
"""
from __future__ import annotations

import json

from src.agents.news.utils.html_parser import extract_text


def test_normal_page_uses_visible_text():
    html = "<html><body><nav>메뉴</nav><article><p>실제 본문 문단.</p><p>둘째 문단.</p></article></body></html>"
    text = extract_text(html)
    assert "실제 본문 문단." in text
    assert "둘째 문단." in text
    assert "메뉴" not in text  # nav 는 스킵


def test_script_is_skipped_for_normal_page():
    html = "<html><body><p>본문</p><script>var x = '스크립트 코드 노이즈';</script></body></html>"
    text = extract_text(html)
    assert text == "본문"  # script 내용은 본문으로 섞이지 않는다


def test_fusion_body_recovered_from_script_json():
    # Arc XP/Fusion: 보이는 텍스트는 짧고, 본문은 Fusion.globalContent 의 content_elements 에 있다.
    global_content = {
        "content_elements": [
            {"type": "text", "content": "첫 번째 본문 문단입니다."},
            {"type": "image", "content": "무시되는 이미지"},
            {"type": "text", "content": "두 번째 <b>본문</b> 문단입니다."},  # 인라인 태그 제거 확인
        ]
    }
    html = (
        "<html><body><nav>메뉴</nav><p>사진 = 연합뉴스</p>"
        "<script id='fusion-metadata'>window.Fusion=window.Fusion||{};"
        f"Fusion.globalContent={json.dumps(global_content, ensure_ascii=False)};"
        "Fusion.globalContentConfig={};</script></body></html>"
    )
    text = extract_text(html)
    assert "첫 번째 본문 문단입니다." in text
    assert "두 번째 본문 문단입니다." in text  # <b> 제거됨
    assert "무시되는 이미지" not in text        # type!=text 는 제외


def test_ldjson_article_body_recovered():
    # schema.org NewsArticle: articleBody 를 ld+json 에서 복구(@graph 중첩 포함).
    ld = {"@graph": [{"@type": "WebPage"}, {"@type": "NewsArticle", "articleBody": "엘디제이 본문 " * 20}]}
    html = (
        "<html><body><p>짧은 보이는 텍스트</p>"
        f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'
        "</body></html>"
    )
    text = extract_text(html)
    assert "엘디제이 본문" in text
    assert len(text) > len("짧은 보이는 텍스트")


def test_longer_visible_text_wins_over_embedded():
    # 임베드 본문이 있어도 보이는 본문이 더 길면 보이는 쪽을 쓴다(정상 기사 회귀 방지).
    ld = {"@type": "NewsArticle", "articleBody": "짧은 임베드"}
    long_body = "긴 본문 문단. " * 50
    html = (
        f"<html><body><article><p>{long_body}</p></article>"
        f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'
        "</body></html>"
    )
    text = extract_text(html)
    assert "긴 본문 문단." in text
    assert "짧은 임베드" not in text


def test_malformed_fusion_json_falls_back_gracefully():
    # 깨진 Fusion JSON 이어도 예외 없이 보이는 텍스트를 반환한다.
    html = (
        "<html><body><p>보이는 본문만 있음</p>"
        "<script>Fusion.globalContent={이건 JSON 아님;</script></body></html>"
    )
    text = extract_text(html)
    assert text == "보이는 본문만 있음"


def test_empty_html():
    assert extract_text("") == ""
