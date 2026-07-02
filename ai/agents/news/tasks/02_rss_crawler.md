# TASK 02 — RSS 수집 & 본문 크롤러 (services/rss.py · services/crawler.py · nodes/crawl.py)

## 0. 개요
- **목적**: 배치 흐름의 첫 두 단계를 만든다. ① 국내 언론사 RSS에서 기사 **목록(메타데이터)**을 수집해 URL 중복을 제거하고, ② 기사 **본문**을 실제로 가져오는 크롤러를 `services/crawler.py`에 재사용 가능한 함수로 둔다. **본문 크롤링은 이 단계에서 일괄 수행하지 않는다.** 본문은 이후 `extract` 노드가 LLM Tool Calling(`fetch_article(url)`)으로 필요한 기사만 가져오며, 그 Tool이 `services/crawler.py`를 내부에서 호출한다.
- **선행 작업**: TASK 01(schemas). `Article` 모델(`title/url/publisher/content/published_at/crawl_status/content_available`)을 그대로 사용한다.
- **산출물(파일)**:
  - `config.py` — RSS 후보 목록·타임아웃·재시도·본문 최소 길이 등 수집/크롤링 설정 (하드코딩 금지의 귀착점)
  - `utils/rss_parser.py` — RSS XML → 원시 기사 항목(dict) 파싱 (순수 함수)
  - `utils/html_parser.py` — 본문 HTML → 태그 제거된 순수 텍스트 추출 (순수 함수)
  - `services/rss.py` — RSS 후보 수집 + URL 정규화 + 중복 제거 → `Article` 메타데이터 리스트
  - `services/crawler.py` — 기사 URL 1건 → 본문 텍스트 반환(재사용 함수). **다른 노드가 직접 호출하지 않는다.**
  - `nodes/crawl.py` — RSS 수집·중복 제거만 담당하는 얇은 노드(본문 크롤링 안 함)
- **범위 밖(주의)**:
  - `fetch_article(url)` **Tool 정의·LLM 등록·Tool Calling 배선은 TASK 03(extract)에서** 한다. TASK 02는 그 Tool이 내부에서 쓸 `services/crawler.py`의 **함수 계약만** 확정한다.
  - 감성·요약·임베딩·병합은 이후 TASK(04/05)다. 여기서는 분석 결과 필드를 채우지 않는다.

### 0.1 하위 의존성 (⚠️ 수정 시 영향 범위)
이 단계는 파이프라인에 들어오는 원자료의 형태·상태를 정한다. 아래 계약을 바꾸면 후속 TASK가 영향받는다.

| 산출물 | 소비하는 TASK |
|---|---|
| `services/rss.py`가 만드는 `Article`(메타데이터, `crawl_status="pending"`) | TASK 03(extract), 04(감성), 05(임베딩·병합), 08(저장) |
| `services/crawler.py.fetch_content(url)` 함수 계약 | TASK 03(`fetch_article` Tool이 내부 호출) |
| `crawl_status` 전이 규칙(pending→success/no_content/failed) | TASK 03(Tool이 상태 확정), 04(본문 없으면 감성 skip) |
| `config.RSS_CANDIDATES` / 타임아웃·재시도 | TASK 10(scheduler가 수집 트리거) |

## 1. 참고 문서
- `docs/pipeline_spec.md` §2(배치 흐름), §4(데이터 수집·RSS 요약을 안 쓰는 이유).
- `docs/sequence.md` §1(배치 시퀀스: rss.py → crawler.py).
- `docs/erd.dbml` — news 테이블 컬럼(`title/content/url/publisher/published_at`), url unique(1차 중복 차단).
- `CLAUDE.md` §2(절대 규칙), §3(배치 흐름), §5(RSS 후보 목록), §7(코딩 컨벤션: 타임아웃·재시도).
- TASK 01 `schemas/article.py` — `Article`, `CrawlStatus`, `content_available`.

## 2. 배경 (왜)
- **왜 RSS 요약을 안 쓰고 본문을 크롤링하나**: 언론사마다 RSS 요약 성격이 다르다(진짜 요약 vs 앞 100자 자르기 vs 없음). 그대로 임베딩하면 같은 사건도 다른 벡터가 나와 병합이 어긋난다. 그래서 본문을 확보해 LLM이 통일된 요약을 만든다 (pipeline_spec §4).
- **왜 본문 크롤링을 이 단계에서 일괄 수행하지 않고 extract의 Tool로 미루나**: 기존 설계는 RSS로 받은 **모든** URL을 먼저 크롤링한 뒤 LLM에 넘겼다. 이 방식은 (1) 분석에 쓰지도 않을 기사까지 본문을 받아 낭비가 크고, (2) 본문 확보 여부·품질 판단이 크롤링 단계에 갇혀 LLM이 개입할 수 없었다. 변경 후에는 LLM이 `fetch_article(url)` Tool로 **필요한 기사만** 본문을 가져오도록 하고, 본문 확보 여부를 LLM이 직접 판단한다. 크롤링 로직을 Tool로 캡슐화해 재사용성을 높이고, "기사 본문 조회"라는 책임을 한 곳(Tool → crawler.py)에 모은다.
- **왜 crawler.py를 삭제하지 않고 유지하나**: 본문을 실제로 가져오는 로직은 여전히 필요하다. 달라지는 것은 "누가 언제 호출하는가"뿐이다. 이제 `services/crawler.py`는 `fetch_article(url)` Tool이 내부에서 호출하는 재사용 함수로 남는다 (CLAUDE.md §2-2: 무거운 로직은 services).
- **왜 crawl 노드는 메타데이터만 준비하나**: `nodes/`는 얇아야 한다(CLAUDE.md §2-2). 본문 조회 책임이 extract의 Tool로 이동했으므로, crawl 노드는 "무엇을 분석 대상 목록에 올릴지"(수집·중복 제거)만 결정한다.
- **왜 상태를 명시적으로 기록하나**: `content=None` 하나로는 "아직 안 가져옴 / 속보라 본문 없음 / 크롤링 실패"를 구분할 수 없다. `crawl_status`로 구분해야 후속 노드가 분기(감성 skip 등)할 수 있고 디버깅이 쉽다 (TASK 01 설계 근거).
- **DB 접근 금지**: 이 단계는 외부(언론사 RSS/기사 페이지)만 읽고, 저장은 하지 않는다. 저장은 TASK 08에서 backend HTTP로만 한다 (CLAUDE.md §2-1).

## 3. 요구사항

### 3.1 `config.py` — 수집/크롤링 설정
1. **RSS_CANDIDATES**: CLAUDE.md §5의 (언론사, URL) 리스트를 그대로 둔다. **하드코딩 금지 원칙에 따라 코드가 아니라 config에서 읽는다** (CLAUDE.md §7).
2. **타임아웃·재시도·유저에이전트**: RSS 요청·본문 요청 각각의 `timeout`(초), `max_retries`, `backoff`(초), `USER_AGENT` 문자열을 둔다. 외부 호출은 반드시 타임아웃·재시도를 갖는다 (CLAUDE.md §7). 언론사 서버가 느리거나 순간 실패할 때 파이프라인 전체가 멈추지 않도록 한다.
3. **MIN_CONTENT_LEN**: 본문으로 인정할 최소 글자 수(예: 200). 이보다 짧으면 "본문 없음(속보)"으로 간주한다. 광고·빈 페이지·짧은 속보를 본문으로 오인해 요약·감성 품질을 떨어뜨리지 않기 위함이다. 임계값은 실데이터 튜닝 대상이므로 주석으로 표기.
4. **CRAWL_MAX_ARTICLES**(선택): 한 배치에서 처리할 최대 기사 수. 초기 폭주 방지용. 미설정 시 무제한.

### 3.2 `utils/rss_parser.py` — RSS 파싱 (순수 함수)
1. RSS/Atom XML 문자열(또는 bytes)을 받아 **원시 기사 항목 리스트**(`title, link, published, description` 등)로 파싱한다. 네트워크 호출은 하지 않는다(입력→출력 순수 함수). 테스트에서 저장된 XML 픽스처로 검증하기 위함.
2. 언론사마다 다른 날짜 포맷(RFC822, ISO8601 등)을 `datetime`(aware, KST 또는 UTC 일관)으로 정규화한다. 발행시각은 7일 롤링 삭제 기준이므로 파싱 실패 시 `None`으로 두되 예외로 파이프라인을 죽이지 않는다.
3. 필수 필드(`title`, `link`)가 없는 항목은 건너뛴다(로깅). 깨진 항목 하나가 전체 피드 파싱을 실패시키지 않도록 항목 단위로 격리한다.

### 3.3 `utils/html_parser.py` — 본문 텍스트 추출 (순수 함수)
1. 기사 페이지 HTML을 받아 **HTML 태그를 제거한 순수 텍스트 본문**을 반환한다. `Article.content`는 원시 HTML이 아니라 순수 텍스트여야 한다(임베딩·요약 품질 및 저장 용량, TASK 01 §3.1).
2. 스크립트/스타일/네비게이션/광고 영역 등 본문이 아닌 노이즈를 최대한 제거한다. 완벽한 본문 추출은 어렵지만, 최소한 태그·공백 정리는 보장한다.
3. 네트워크 호출 없음(입력 HTML → 출력 텍스트). 크롤러(`services/crawler.py`)가 받아온 HTML을 이 함수로 정제한다.

### 3.4 `services/rss.py` — RSS 수집 + 중복 제거
1. `RSS_CANDIDATES`의 각 피드를 요청(타임아웃·재시도)하고 `utils/rss_parser.py`로 파싱한다. 한 피드가 실패해도 나머지 피드는 계속 수집한다(피드 단위 격리, 예외는 로깅). CLAUDE.md §7: 실패한 건 skip하되 파이프라인은 계속.
2. **URL 정규화 후 중복 제거**: 같은 기사가 여러 피드/추적 파라미터로 중복 유입되므로, URL을 정규화(쿼리스트링 `utm_*` 제거, fragment 제거, scheme/host 소문자화 등)한 뒤 중복을 제거한다. `url`은 1차 중복 차단 키다(erd.dbml, TASK 01: url 필수·unique).
3. 결과를 **`Article` 메타데이터 리스트**로 반환한다. 이 단계에서 채우는 필드는 `title, url, publisher, published_at`뿐이다. **본문은 가져오지 않으므로** `content=None`, `crawl_status="pending"`, `content_available=False`로 둔다(분석 결과 필드도 모두 None).
4. `publisher`는 RSS_CANDIDATES의 언론사명으로 채운다(importance 가중치에서 사용, TASK 06).
5. **본문·RSS description으로 분석하지 않는다**: RSS의 `description`(요약)은 병합·감성에 쓰지 않는다(품질 불균일, pipeline_spec §4). 보관이 필요하면 별도 필드가 아닌 로깅/디버깅 용도로만 다루고, `Article.content`에 넣지 않는다.

### 3.5 `services/crawler.py` — 본문 크롤러 (재사용 함수, 유지)
1. **함수 계약**: 기사 URL 1건을 입력받아 본문 텍스트와 상태를 반환한다. 다른 노드는 이 함수를 직접 호출하지 않으며, **오직 `extract`의 `fetch_article(url)` Tool을 통해서만** 호출된다(TASK 03). Tool 원칙(변경사항 §6)을 코드 위치로 강제한다.
2. **반환 상태 매핑**(TASK 01 `CrawlStatus`와 정합):
   | 상황 | content | crawl_status | content_available |
   |------|---------|--------------|-------------------|
   | 본문 정상 확보(길이 ≥ `MIN_CONTENT_LEN`) | 순수 텍스트 | `"success"` | `True` |
   | 속보/본문 없음(길이 < `MIN_CONTENT_LEN`) | `None` | `"no_content"` | `False` |
   | 요청 실패(타임아웃·4xx/5xx·파싱 불가) | `None` | `"failed"` | `False` |
3. HTML은 `utils/html_parser.py`로 정제해 순수 텍스트로 만든다. 원시 HTML을 반환하지 않는다.
4. 외부 호출이므로 `config`의 타임아웃·재시도·USER_AGENT를 적용한다. 예외는 삼키지 말고 로깅한 뒤 `crawl_status="failed"`로 반환한다(호출측이 분기할 수 있도록). CLAUDE.md §7.
5. **함수는 순수 조회에 가깝게**: 입력 URL → 출력(본문/상태). 부수효과(저장 등) 없음. 재사용성과 테스트 용이성을 위함.

### 3.6 `nodes/crawl.py` — 수집 노드 (얇게, 본문 크롤링 안 함)
1. `services/rss.py`를 호출해 중복 제거된 `Article` 메타데이터 리스트를 얻어 파이프라인 state에 실어 넘긴다. 노드는 순서만 담당하는 얇은 껍데기다(CLAUDE.md §2-2).
2. **본문을 크롤링하지 않는다.** 본문 조회는 다음 단계(`extract`)의 Tool Calling이 수행한다. crawl 노드는 "분석 대상 목록"을 확정하는 역할만 한다.
3. `CRAWL_MAX_ARTICLES`가 설정돼 있으면 상한을 적용한다(발행시각 최신순 등 명시적 기준으로 자른다).
4. 수집 0건이어도 예외 없이 빈 리스트를 넘긴다(환각 금지: 데이터가 없으면 없는 대로 넘긴다, CLAUDE.md §2-5). 후속 노드가 "데이터 제한"으로 처리한다.

## 4. 인터페이스 / 구현 규칙

> 아래는 확정 시그니처(초안). 함수명·반환 타입은 이대로 구현하되, 설정값은 `config.py`에서 읽는다.

```python
# config.py (발췌) — 수집/크롤링 설정. 값은 실데이터 튜닝 대상(주석 표기).
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

RSS_TIMEOUT: float = 10.0          # RSS 요청 타임아웃(초)
CRAWL_TIMEOUT: float = 10.0        # 본문 요청 타임아웃(초)
MAX_RETRIES: int = 2               # 외부 호출 재시도 횟수
RETRY_BACKOFF: float = 1.0         # 재시도 간 대기(초)
USER_AGENT: str = "verith-news-agent/1.0"
MIN_CONTENT_LEN: int = 200         # 본문 인정 최소 글자수(미만이면 no_content) — 튜닝 대상
CRAWL_MAX_ARTICLES: int | None = None   # 배치당 최대 처리 기사 수(None=무제한)
```

```python
# utils/rss_parser.py — 순수 파싱(네트워크 없음)
from __future__ import annotations
from datetime import datetime

def parse_rss(xml: str | bytes, publisher: str) -> list[dict]:
    """RSS/Atom XML → 원시 기사 항목 리스트.
    각 항목: {"title": str, "link": str, "published_at": datetime | None,
             "publisher": str, "description": str | None}
    - title/link 없는 항목은 skip(로깅).
    - 날짜 포맷은 datetime(aware)으로 정규화. 실패 시 None.
    """
    ...
```

```python
# utils/html_parser.py — 순수 텍스트 추출(네트워크 없음)
from __future__ import annotations

def extract_text(html: str) -> str:
    """기사 HTML → 태그 제거된 순수 텍스트 본문.
    script/style/nav/광고 영역 제거, 공백 정리. 원시 HTML을 반환하지 않는다.
    """
    ...
```

```python
# services/rss.py — 수집 + 중복 제거(본문 크롤링 안 함)
from __future__ import annotations
from schemas.article import Article

def normalize_url(url: str) -> str:
    """추적 파라미터(utm_*)·fragment 제거, scheme/host 소문자화. 중복 제거 키."""
    ...

def collect_articles() -> list[Article]:
    """RSS_CANDIDATES 전체 수집 → 파싱 → URL 정규화·중복 제거.
    반환 Article은 메타데이터만 채움:
      title, url, publisher, published_at 세팅
      content=None, crawl_status="pending", content_available=False
    피드 단위로 실패 격리(한 피드 실패해도 나머지 계속, 예외 로깅).
    """
    ...
```

```python
# services/crawler.py — 본문 크롤러(재사용 함수, 유지)
# ⚠️ 다른 노드에서 직접 import·호출 금지. extract의 fetch_article(url) Tool만 호출.
from __future__ import annotations
from dataclasses import dataclass
from schemas.article import CrawlStatus

@dataclass
class CrawlResult:
    content: str | None
    crawl_status: CrawlStatus      # "success" | "no_content" | "failed"
    content_available: bool

def fetch_content(url: str) -> CrawlResult:
    """기사 URL 1건 → 본문 텍스트 + 상태.
    - HTML은 utils.html_parser.extract_text로 순수 텍스트화.
    - 길이 >= MIN_CONTENT_LEN: success / < : no_content / 요청·파싱 실패: failed.
    - config의 타임아웃·재시도·USER_AGENT 적용. 예외는 로깅 후 failed 반환.
    - 부수효과 없음(저장 안 함).
    """
    ...
```

```python
# nodes/crawl.py — 얇은 수집 노드(본문 크롤링 안 함)
from __future__ import annotations
import services.rss as rss
from config import CRAWL_MAX_ARTICLES

def crawl_node(state: dict) -> dict:
    """RSS 수집·중복 제거만. 본문 조회는 extract의 Tool Calling에서 수행.
    state["articles"]에 메타데이터 Article 리스트를 실어 넘긴다.
    """
    articles = rss.collect_articles()
    if CRAWL_MAX_ARTICLES:
        articles = articles[:CRAWL_MAX_ARTICLES]   # 최신순 등 명시 기준으로 자름
    state["articles"] = articles
    return state
```

> **`fetch_article(url)` Tool(TASK 03에서 정의)의 계약 미리보기** — TASK 02는 아래를 만족하도록 `crawler.fetch_content`를 제공한다. Tool은 URL 하나를 받아 본문(과 상태)만 반환하고, 내부에서 `services/crawler.py`를 사용한다. LLM은 이 Tool이 반환한 본문만 근거로 추출하며, RSS의 title/description만으로는 분석하지 않는다.

```python
# (TASK 03에서 구현) extract.py 내부 Tool — 여기서는 계약만 표시
def fetch_article(url: str) -> dict:
    """LLM Tool. services.crawler.fetch_content(url)를 호출해 본문/상태 반환.
    반환: {"content": str | None, "crawl_status": ..., "content_available": bool}
    """
    ...
```

### 4.1 본문 없는 기사 처리 규칙 (환각 금지)
본문을 가져오지 못해도 추측해서 분석하지 않는다(CLAUDE.md §2-5). 상태에 따라 다음과 같이 처리한다.

| 상황 | 처리 |
|------|------|
| 본문 존재(`success`) | 본문 기반 LLM 추출 + 감성 분석 |
| 속보/본문 없음(`no_content`) | 제목만 사용. LLM은 제목으로 확인 가능한 정보만 추출 |
| 크롤링 실패(`failed`) | Skip 또는 오류 상태로 기록(파이프라인은 계속) |

- **제목만 사용하는 경우**(`no_content`)의 기록 규칙:
  - `summary = "<기사 제목> (본문 없음)"`
  - `content_available = False`, `crawl_status = "no_content"`
  - `ExtractResult.source_type = "title_only"` (본문 기반이면 `"article"`, TASK 01 §3.1)
  - LLM은 본문에 있을 것으로 **추정되는 내용을 생성·보완하지 않는다.**
- **감성 분석 입력**(TASK 04 연계, 여기서는 계약만 명시): KR-FinBert는 **기사 본문 전체**를 입력으로 쓴다. 본문이 없으면(`no_content`) 제목만으로 감성을 추론하지 않고 감성 분석을 **수행하지 않거나 정책에 따라 Skip**한다. 그래서 `crawl_status`를 후속 노드가 반드시 참조할 수 있도록 정확히 기록해야 한다.

### 4.2 Tool Calling 책임 분리 (변경사항 §6)
- Tool(`fetch_article`)은 **`extract.py`에서만** 호출한다(TASK 03). 다른 노드는 Tool도 `crawler.py`도 직접 호출하지 않는다.
- Tool은 기사 URL **하나**를 입력받아 기사 **본문만** 반환한다(단일 책임).
- Tool 내부에서는 `services/crawler.py`를 사용한다.
- 이 분리를 코드 위치·import 방향으로 강제한다: `nodes/crawl.py`는 `services/crawler.py`를 import 하지 않는다.

## 5. 규칙·제약 (CLAUDE.md)
- **§2-1 DB 직접 접근 금지.** 이 단계는 외부 RSS/기사 페이지만 읽는다. 저장·조회는 없다(TASK 08에서 backend HTTP).
- **§2-2 nodes는 얇게, 로직은 services에.** `nodes/crawl.py`는 `services/rss.py` 호출만. 크롤링·파싱 로직은 `services/`·`utils/`에 둔다.
- **§2-5 환각 금지.** 본문 없으면 지어내지 않는다. `no_content`/`failed`를 명시하고, 제목만 쓸 때 `source_type="title_only"`로 표시.
- **§4 감성은 전용 모델.** crawler는 본문을 확보만 한다. 감성 판정은 하지 않는다(TASK 04).
- **§5 RSS 후보 목록은 config.** 코드에 URL을 흩뿌리지 않는다.
- **§7 외부 호출은 타임아웃·재시도.** RSS·본문 요청 모두 적용. 실패는 skip하되 파이프라인 계속. 예외는 삼키지 말고 로깅.
- **§7 설정값 하드코딩 금지.** 타임아웃·재시도·`MIN_CONTENT_LEN`·상한은 `config.py`에서 읽는다.
- **변경사항 §3 crawler.py 유지.** 삭제하지 않는다. Tool이 내부에서 재사용한다.

## 6. 완료 조건 (DoD)
- [ ] `config.py`에 `RSS_CANDIDATES`(CLAUDE.md §5 그대로)와 `RSS_TIMEOUT/CRAWL_TIMEOUT/MAX_RETRIES/RETRY_BACKOFF/USER_AGENT/MIN_CONTENT_LEN/CRAWL_MAX_ARTICLES`가 정의됨.
- [ ] `utils/rss_parser.parse_rss`가 XML을 원시 항목 리스트로 파싱하고, 날짜를 `datetime`으로 정규화하며, title/link 없는 항목을 skip함(네트워크 호출 없음).
- [ ] `utils/html_parser.extract_text`가 HTML → 순수 텍스트를 반환함(태그·script/style 제거).
- [ ] `services/rss.collect_articles`가 전체 피드를 수집·파싱하고, `normalize_url`로 중복을 제거해 `Article` 메타데이터 리스트를 반환함. 한 피드 실패가 전체를 죽이지 않음.
- [ ] `collect_articles`가 반환하는 `Article`은 `content=None`, `crawl_status="pending"`, `content_available=False`이고 `title/url/publisher/published_at`만 채워짐. **본문을 크롤링하지 않음.**
- [ ] `services/crawler.fetch_content(url)`가 `CrawlResult`를 반환하며 상태 매핑(success/no_content/failed)이 §3.5 표대로 동작함. 본문은 순수 텍스트, 원시 HTML 아님.
- [ ] `nodes/crawl.py`가 `services/rss.py`만 호출하고 **`services/crawler.py`를 import 하지 않음**(본문 크롤링을 하지 않음). 상한(`CRAWL_MAX_ARTICLES`) 적용됨.
- [ ] 본문 없는 기사 규칙(§4.1)이 문서·구현에 반영됨: `no_content` 시 `summary="<제목> (본문 없음)"`, `source_type="title_only"`, 추정 생성 없음.
- [ ] `crawl_status`/`content_available`가 항상 정합됨(`success` ↔ `content_available=True`).
- [ ] 수집 0건일 때 예외 없이 빈 리스트를 넘김.

## 7. 테스트
- **대상 파일**: `tests/test_crawler.py`(존재), 필요 시 `tests/test_rss.py` 추가.
- **mock 전략**: 외부 네트워크는 절대 실제 호출하지 않는다. RSS XML·기사 HTML은 저장된 픽스처로 대체하고, HTTP 클라이언트는 mock한다(CLAUDE.md: tests는 mock 기반).
  - `parse_rss`: 언론사별 실제 XML 샘플(각 1~2개)로 항목 수·title·link·published_at 파싱 검증. 깨진/필드 누락 항목이 skip되는지.
  - `extract_text`: script/style/태그가 제거되고 순수 텍스트만 남는지. 원시 HTML이 반환되지 않는지.
  - `normalize_url`: `utm_*`·fragment 제거, 동일 기사의 변형 URL이 같은 키로 접히는지(중복 제거 검증).
  - `collect_articles`: 한 피드가 예외를 던져도 나머지 피드 결과가 반환되는지(실패 격리). 반환 Article의 `crawl_status=="pending"`, `content is None`.
  - `fetch_content`: (1) 충분히 긴 본문 → `success`/`content_available=True`, (2) 짧은 본문 → `no_content`, (3) 타임아웃/HTTP 오류 mock → `failed`. 각 경우 `content`와 상태의 정합.
- **경계 케이스**: RSS 0건, 날짜 파싱 실패(→None), 중복 URL 다수, 본문 길이 = `MIN_CONTENT_LEN` 경계.
- **evals 연계**: 없음(수집·크롤링은 tests 레벨 검증). 추출·감성 품질은 이후 evals 축에서 다룬다.
- 후속 TASK(03 extract의 `fetch_article` Tool)가 `crawler.fetch_content` 계약을 재사용하므로, 반환 타입·상태 매핑을 바꾸면 여기부터 수정한다.
