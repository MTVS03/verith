# config.py
"""news 에이전트 수집/크롤링 설정.

CLAUDE.md §7: 설정값(타임아웃·재시도·임계값·상한·보안 상수)은 코드에 흩뿌리지 않고
여기서 읽는다. 아래 값 중 임계값·상한은 실데이터 튜닝 대상이며 주석으로 표기한다.

TASK 03(extract) 이후 프롬프트/모델 관련 설정, TASK 05~08의 병합 가중치·backend 경로
등은 각 TASK에서 이 파일에 추가한다. 이 단계(TASK 02)는 RSS 수집·본문 크롤 설정만 둔다.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# RSS 후보 목록 (CLAUDE.md §5 그대로). 코드가 아니라 config에서 읽는다(하드코딩 금지).
# (언론사명, 피드 URL). publisher는 importance 가중치(TASK 06)에서 사용.
# ---------------------------------------------------------------------------
RSS_CANDIDATES: list[tuple[str, str]] = [
    ("조선일보", "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml"),
    ("동아일보", "https://rss.donga.com/total.xml"),
    ("경향신문", "https://www.khan.co.kr/rss/rssdata/total_news.xml"),
    ("세계일보", "https://www.segye.com/Articles/RSSList/segye_recent.xml"),
    ("매일경제", "https://www.mk.co.kr/rss/40300001/"),
    ("한국경제", "https://www.hankyung.com/feed/all-news"),
    ("한겨레", "https://www.hani.co.kr/rss"),
    ("디지털타임스", "https://www.dt.co.kr/rss/google/latest"),
    ("아시아경제", "https://view.asiae.co.kr/rss/all.htm"),
    ("파이낸셜뉴스", "https://www.fnnews.com/rss/r20/fn_realnews_all.xml"),
]

# ---------------------------------------------------------------------------
# 외부 호출 공통 (RSS·본문). 모든 외부 호출은 타임아웃·재시도를 갖는다(CLAUDE.md §7).
# ---------------------------------------------------------------------------
RSS_TIMEOUT: float = 10.0          # RSS 요청 타임아웃(초)
CRAWL_TIMEOUT: float = 10.0        # 본문 요청 타임아웃(초)
MAX_RETRIES: int = 2               # 외부 호출 재시도 횟수(총 시도 = 1 + MAX_RETRIES)
RETRY_BACKOFF: float = 1.0         # 재시도 간 대기(초)
USER_AGENT: str = "verith-news-agent/1.0"

# ---------------------------------------------------------------------------
# 본문 인정/상한. 임계값·상한은 튜닝 대상.
# ---------------------------------------------------------------------------
MIN_CONTENT_LEN: int = 200         # 본문 인정 최소 글자수(미만이면 no_content=속보) — 튜닝 대상
CRAWL_MAX_ARTICLES: int | None = None   # 배치당 최대 처리 기사 수(None=무제한, 초기 폭주 방지용)

# ---------------------------------------------------------------------------
# 크롤러 안전장치 (SSRF·자원 고갈 방어) — TASK 02 §3.5-6. 보안 상수도 config에.
# 크롤러는 넘겨받은 URL을 신뢰하지 않는다. 요청 전·리다이렉트 매 홉마다 검사한다.
# ---------------------------------------------------------------------------
CRAWL_ALLOWED_SCHEMES: set[str] = {"http", "https"}          # 그 외 scheme(file:/ftp:/gopher: 등) 요청 거부
CRAWL_BLOCK_PRIVATE_IPS: bool = True                          # 사설/루프백/링크로컬/메타데이터 대역 차단(리다이렉트 최종지 포함)
CRAWL_MAX_REDIRECTS: int = 5                                  # 리다이렉트 추적 최대 홉(초과 시 failed)
CRAWL_MAX_RESPONSE_BYTES: int = 5_000_000                     # 응답 본문 다운로드 상한(초과 시 중단·failed)
CRAWL_ALLOWED_CONTENT_TYPES: set[str] = {"text/html", "application/xhtml+xml"}  # 본문 응답 허용 Content-Type
ARTICLE_CONTENT_MAX_CHARS: int = 50_000    # Article.content 저장 텍스트 상한 — 튜닝 대상.
#                                            EXTRACT_CONTENT_MAX_CHARS(TASK 03, 프롬프트 입력 상한)와 별개.
