# TASK 01 — 스키마 정의 (schemas/)

## 0. 개요
- **목적**: 파이프라인 전 구간에서 주고받는 데이터를 Pydantic v2 모델로 정의한다. 이후 모든 TASK가 이 스키마를 import 하므로 가장 먼저 확정한다.
- **선행 작업**: 없음 (최초 작업).
- **산출물(파일)**:
  - `schemas/article.py` — 기사 원본(Article) + LLM 추출 결과(ExtractResult) + `SourceType`·`EventCandidate`(TASK 03) + `SentimentResult`(TASK 04)
  - `schemas/event.py` — 이벤트(Event) + 병합 모델(MergeCandidate/MergeDecision) + `CandidateEvent`(TASK 05) + `EventArticleStats`(TASK 06)
  - `schemas/report.py` — HTML 리포트 입력 모델(감성 게이지 + TOP 이벤트)
  - `schemas/response.py` — backend 조회 응답 래퍼
  - `schemas/__init__.py` — 위 모델 재노출(re-export)
- **범위 밖(주의)**: `schemas/graph.py`(Neo4j 노드/관계 상세 모델)는 **TASK 07**에서 정의한다. 여기서는 Event의 개념 필드만 잡는다.

### 0.1 하위 의존성 (⚠️ 수정 시 영향 범위)
이 스키마는 파이프라인의 계약이다. 필드명·타입을 바꾸면 아래 TASK가 **모두** 영향받으므로, 함부로 수정하지 말고 바꿔야 하면 여기부터 고치고 영향 TASK를 함께 갱신한다.

| 모델 | 소비하는 TASK |
|---|---|
| `ExtractResult` / `EventCandidate` | TASK 03(extract 생성) → TASK 05(임베딩·병합) → TASK 07(그래프) → TASK 08(저장) |
| `SourceType` | TASK 03(추출 경로 표시), 05(신뢰도), 08(저장) |
| `Article` | TASK 02(크롤링), 03, 04(감성), 05(임베딩·병합), 08(저장) |
| `SentimentResult` | TASK 04(감성 서비스 반환), 06(강도 소비) |
| `Event` / `MergeDecision` | TASK 05(병합), 06(importance), 07(그래프), 08(저장) |
| `CandidateEvent` | TASK 05(병합 후보), 08(BackendRecentEventProvider가 반환) |
| `EventArticleStats` | TASK 06(importance 재계산), 08(BackendEventArticleStatsProvider가 반환) |
| `SentimentGauge` / `ArticleRef` / `ReportEvent` / `ReportModel` | TASK 09(리포트 렌더링) |
| `SubjectQueryResponse` / `EventWithArticles` / `SaveResponse` / `CleanupResponse` | TASK 08(backend 클라이언트), 09(리포트), 10(스케줄러 삭제) |

## 1. 참고 문서
- `docs/erd.dbml` — news 테이블 컬럼, Neo4j Event 구조, 삭제 규칙, importance 공식.
- `docs/pipeline_spec.md` §5(LLM 추출 항목), §7(저장), §9(importance).
- `docs/event_merge.md` §6(canonical_title, 감성 평가어 금지).
- `CLAUDE.md` §3(모델 스택), §5(핵심 로직 규칙), §7(코딩 컨벤션).

## 2. 배경 (왜)
- **왜 Pydantic으로 강제하나**: LLM 추출 결과를 "JSON 반환"에만 의존하면 파싱 실패·필드 누락이 생긴다. `schemas/`의 모델로 파싱·검증해 실패를 조기에 잡는다 (CLAUDE.md §2-3).
- **왜 스키마를 먼저 만드나**: 크롤링→추출→감성→임베딩→병합→저장→리포트가 모두 같은 데이터 구조를 공유한다. 구조가 흔들리면 모든 노드가 흔들리므로 계약(contract)을 먼저 고정한다.
- **DB 스키마와의 관계**: 실제 테이블은 backend가 생성한다(erd.dbml 주석). 이 파일들은 **에이전트가 backend에 보내고/받는 요청·응답 명세**이지 ORM 모델이 아니다. DB 드라이버·SQL 금지 (CLAUDE.md §2-1).

## 3. 요구사항

### 3.1 `schemas/article.py`
1. **개체(추출 대상)**: 회사·인물·산업·국가·키워드는 모두 **문자열 리스트**로 다룬다. 지금은 이름 외 속성(ticker 등)이 없으므로 별도 개체 모델을 만들지 않는다. (안 쓰는 모델은 유지보수 비용·혼란만 늘린다. ticker 등 실제 속성이 필요해지는 시점에 그때 `Company` 모델을 도입한다.)
2. **ExtractResult**: LLM이 기사 1건에서 뽑는 결과. pipeline_spec §5의 항목을 반영 → `summary, companies, people, industries, events, countries, keywords, event_date`. **감성·영향도 필드는 두지 않는다**(감성=FinBert, 영향도=importance가 담당, CLAUDE.md §4).
   - **events는 문자열이 아니라 `EventCandidate`(title+confidence) 리스트**다. 같은 기사라도 이벤트마다 확신도가 달라, 병합(TASK 05)이 약한 후보를 낮게 반영·필터할 수 있게 한다. `title`은 사건명만(회사명·감성 평가어 금지, TASK 03 §3.2.2).
   - **event_date**(`datetime | None`): 이벤트 발생 시점. `Article.published_at`(발행)과 별개(예: "지난주 계약"을 오늘 보도). 병합의 시간 근접도·타임라인에 쓴다. 불확실하면 `None`(지어내지 않음).
   - **source_type**(`SourceType` Enum 3종): 본문 기반(`article`)·(향후) RSS 요약(`rss_summary`, 현재 미생성)·제목만(`title_only`). 병합·리포트에서 신뢰도 구분에 쓴다.
   - ※ **EventCandidate**(TASK 03 후보 이벤트)·**SentimentResult**(TASK 04 감성 결과)도 여기 `schemas`에 둔다(services dataclass 아님). 서비스·노드·테스트가 같은 계약을 공유하기 위함.
3. **Article / News**: erd.dbml의 news 테이블을 반영. 크롤링 직후(요약·감성·임베딩 전) → 분석 후(요약·감성·임베딩 채워짐)까지 파이프라인을 따라 필드가 점진적으로 채워지므로, 분석 결과 필드는 모두 Optional로 둔다.
   - 크롤링 단계에서 채우는 필드: `title, url, publisher, content, published_at`. **`content`는 HTML 태그를 제거한 순수 텍스트 본문**이다(원시 HTML을 그대로 담지 않는다 → 임베딩·요약 품질 및 저장 용량 문제 방지).
   - **crawl_status**(`pending|success|no_content|failed`): `content=None`만으로는 "미크롤링 / 본문없음(속보) / 실패"를 구분할 수 없다. 상태를 명시해 디버깅·Tool Calling 분기를 쉽게 한다.
   - **content_available**(bool): 본문 유무 편의 플래그. `crawl_status == "success"`와 항상 정합을 유지하도록 채운다(둘이 어긋나지 않게).
   - 분석 단계에서 채우는 필드(초기 None): `summary, sentiment, sentiment_score, embedding, event_id`.
   - **sentiment_score**: KR-FinBert가 주는 confidence(0~1). importance 계산·리포트 표시에 활용(감성 자체는 여전히 전용 모델 판정, CLAUDE.md §4).
   - **analysis_completed**(bool): 분석 파이프라인(요약·감성·임베딩·병합)이 정상 완료됐는지. `summary=None`·`event_id=None`이 "아직 안 함"인지 "하다 실패"인지 구분하는 최종 플래그. `crawl_status`(수집 단계)와 짝을 이뤄 기사의 처리 상태를 명확히 한다.
4. `url`은 중복 차단 키이므로 필수. `sentiment`는 값 3종(긍정/중립/부정)만 허용하도록 Enum으로 제약.

### 3.2 `schemas/event.py`
1. **Event**: Neo4j 중심 노드의 개념 모델. erd.dbml Neo4j 구조 반영 → `canonical_id, canonical_title, importance`.
   - **용어 통일**: 이벤트의 대표 식별자는 문서·코드 모두 **`canonical_id`**로 부른다(`id`로 쓰지 않는다). "DB id인가 canonical인가" 혼동을 없앤다.
   - **타입은 UUID 문자열(`str`)**. `Article.event_id`, `MergeCandidate.event_id`, `MergeDecision.assigned_event_id`는 이 `canonical_id`를 가리키는 외래 참조이므로 **모두 같은 `str` 타입**으로 맞춘다. **erd.dbml·SCHEMA_SPEC의 `news.event_id`도 `uuid`로 정합**시켰다(정수 PK는 `news.id`(=news_id)뿐). backend 저장 컬럼 타입은 TASK 08/SCHEMA_SPEC와 합의.
2. **canonical_title 규칙 명시**: 사실만, 감성 평가어 금지("실적 발표" O / "실적 호조" X). 검증까지는 어렵지만 docstring/주석으로 규칙을 남긴다 (event_merge.md §6).
3. **감성 count 필드를 두지 않는다**: Event에 집계값을 저장하지 않고 조회 시 실시간 집계 (erd.dbml, CLAUDE.md §5). 따라서 Event 모델에는 count류 필드가 없어야 한다. (단, `created_at`(최초 생성 시각)은 집계값이 아니라 관리·정렬용 메타이므로 둔다.)
4. **병합 판정 결과 모델**: 새 기사가 기존 이벤트에 편입되는지/신규인지, 그리고 후보별 score를 담는 결과 모델(MergeDecision류)을 둔다. 세부 병합 로직은 TASK 05지만, 결과 자료구조는 여기서 정의한다.
5. **CandidateEvent**(TASK 05): 병합 후보 이벤트 조회 결과(`canonical_id·companies·embedding(centroid)·event_time`). centroid 계산·유지는 backend, 여기선 계약만.
6. **EventArticleStats**(TASK 06): 기존(저장된) 이벤트의 누적 통계(`article_count·publishers·sentiment_magnitude_sum·sentiment_count`). importance 전체 재계산 시 이번 배치와 합산하는 입력.

### 3.3 `schemas/report.py`
1. HTML 리포트(pipeline_spec §1: 감성 게이지 + TOP 이벤트)의 입력 모델.
2. **SentimentGauge**: 긍/중/부 분포(집계 결과). 비율 또는 건수.
3. **ArticleRef**: 근거 기사 한 건 = `news_id` + `summary` + `url`을 **하나의 객체로 묶는다**. 요약 리스트와 URL 리스트를 따로 두면 순서가 어긋나 summary와 엉뚱한 url이 연결되는 버그가 생긴다. 항상 같이 움직이는 값은 한 객체로 묶는다. **`news_id`(= `Article.id`)를 포함**해 질의 흐름의 근거 news_id 사슬(TASK 09 §0.2)이 화면 기사→news_id로 역추적되게 한다(없으면 evidence 추적이 끊긴다).
4. **ReportEvent**: 리포트에 노출되는 이벤트 한 건 = canonical_title + importance + 감성 분포 + `article_count`(관련 기사 총 건수, "관련 기사 42건" 표시용) + 근거 기사(`list[ArticleRef]`) 소수. **`article_count`는 전체 집계, `articles`는 화면에 보일 대표 소수**로 구분한다(두 값의 의미가 다름).
5. **ReportModel**: 종목(입력) + 생성 시각 + SentimentGauge + TOP ReportEvent 리스트. 데이터 부족 시 "데이터 제한" 표기를 담을 수 있는 필드/플래그를 둔다 (CLAUDE.md §2-5, 환각 금지).

### 3.4 `schemas/response.py`
1. backend 조회 응답을 감싸는 래퍼. sequence.md §2(리포트 흐름)에서 query_client가 받는 형태.
2. 종목 조회 결과 = 이벤트(importance순) + 각 이벤트의 근거 기사(`ArticleRef` 재사용) + **전체 `overall_gauge`**(backend가 채우는 전체 감성 집계, `sentiment=None` 제외). ReportModel 조립에 필요한 원자료를 담는다. **overall_gauge는 backend 집계값**이며 ai가 기사 감성을 다시 세지 않는다(절대규칙 4, SCHEMA_SPEC §7.3).
   - **대표 기사 vs 근거 조회 분리**: `EventWithArticles.articles`는 화면용 **대표 소수**이고, `ArticleRef`가 news_id를 이미 포함하므로 일반 리포트는 이 대표 소수만으로 근거를 단다(재조회 불필요). 대표 소수를 넘는 추가 근거가 필요할 때만 **on-demand로 `get_articles_by_event(event_id, limit)`**(TASK 08·SCHEMA_SPEC §7.2)로 조회한다. 이벤트별 전체 news_id를 DTO에 상시 싣지 않아 조회 DTO가 가볍다(책임 분리).
3. **"없는 종목" vs "뉴스 0건" 구분**: 둘 다 `events=[]`가 되므로, `subject_found: bool` 플래그로 구분한다. 리포트에서 "데이터 제한" 문구를 상황에 맞게 쓰기 위함(당장 backend가 구분값을 못 주면 기본 True로 두고 TASK 08에서 확정).
4. 저장/삭제 요청·응답의 성공 여부·개수 등 backend 공통 응답 형태도 여기서 정의(세부 엔드포인트 계약은 TASK 08에서 확정하되, 모델 골격은 여기 둔다).

### 3.5 `schemas/__init__.py`
- 위 모델들을 패키지 레벨에서 import 가능하도록 재노출한다. (`from schemas import Article, ExtractResult, Event, ReportModel ...`)

## 4. 인터페이스 / 모델 정의

> 아래는 확정 시그니처(초안). 필드명·타입은 이대로 구현하되, 실데이터로 조정 가능한 값은 주석 표기.

```python
# schemas/article.py
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl

class Sentiment(str, Enum):
    POSITIVE = "긍정"
    NEUTRAL  = "중립"
    NEGATIVE = "부정"

# 크롤링 진행/결과 상태. content=None만으로는 "미크롤링 / 본문없음(속보) / 실패"를 구분 못 함.
CrawlStatus = Literal["pending", "success", "no_content", "failed"]

class SourceType(str, Enum):
    ARTICLE = "article"          # 본문 기반 추출
    RSS_SUMMARY = "rss_summary"  # (향후) RSS 요약 기반 — 현재 미사용, Enum만 예약
    TITLE_ONLY = "title_only"    # 제목만 사용(본문 없음)

class EventCandidate(BaseModel):
    """LLM이 기사에서 뽑은 원시 후보 이벤트(TASK 03). 대표 Event·canonical_title은 TASK 05가 생성."""
    title: str          # 사건명만(회사명 금지: "HBM 공급 계약" O / "삼성전자 HBM 공급 계약" X). 감성 평가어 금지
    confidence: float   # 0~1 추출 확신도(importance·감성 세기가 아님). 병합(TASK 05)이 가중·필터에 사용

class ExtractResult(BaseModel):
    """LLM(Qwen3)이 기사 1건에서 추출한 결과. 감성·영향도 없음."""
    summary: str
    companies: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    events: list[EventCandidate] = Field(default_factory=list)   # 원시 후보 이벤트(title+confidence, TASK 03)
    countries: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    # 이벤트 발생 시점(KST aware). Article.published_at(발행)과 별개. 상대표현은 published_at 기준 환산,
    # 날짜만 있으면 00:00(KST), 불명확/판단불가면 None(지어내지 않음). 정규화 규칙 TASK 03 §3.2.1.
    event_date: datetime | None = None
    # 본문 기반/RSS요약/제목만. 병합·리포트 신뢰도 판단에 활용(rss_summary는 현재 미생성).
    source_type: SourceType = SourceType.ARTICLE

class Article(BaseModel):
    """기사 원본 + 분석 결과. 파이프라인을 따라 점진적으로 채워짐."""
    # 크롤링 단계
    title: str
    url: HttpUrl                    # 중복 차단 키(필수)
    publisher: str | None = None    # importance 가중치에 사용
    content: str | None = None      # HTML 태그 제거 후 순수 텍스트 본문(크롤링 실패 시 None → skip)
    published_at: datetime | None = None
    crawl_status: CrawlStatus = "pending"   # 크롤링 상태. 디버깅·Tool Calling 분기용
    content_available: bool = False         # 편의 플래그(= crawl_status == "success"와 정합 유지)
    # 분석 단계 (초기 None)
    summary: str | None = None      # LLM 통일 요약. 임베딩·병합 기준
    sentiment: Sentiment | None = None
    sentiment_score: float | None = None   # KR-FinBert confidence(0~1). importance·리포트에 활용
    # arctic-embed-l-v2.0-ko에서 생성한 summary 임베딩 (services/embedder.py).
    # 대칭 유사도 비교라 query/document 프리픽스 없이 임베딩(event_merge.md §2). 차원은 모델 스펙 따름.
    embedding: list[float] | None = None
    event_id: str | None = None            # 소속 이벤트의 canonical_id(UUID). 병합 전 None
    # 분석 파이프라인(요약·감성·임베딩·병합) 정상 완료 여부.
    # summary/event_id가 None인 게 "아직 안 함"인지 "하다 실패"인지 구분하는 최종 플래그.
    analysis_completed: bool = False
    # backend가 채우는 식별자
    id: int | None = None
    created_at: datetime | None = None

class SentimentResult(BaseModel):
    """감성 판정 결과(TASK 04). services dataclass가 아니라 schemas에 두어 서비스·노드·테스트가 공유."""
    sentiment: Sentiment   # 긍정|중립|부정 (모델 라벨 → FINBERT_LABEL_MAP 매핑)
    score: float           # = Article.sentiment_score. 예측 라벨 confidence(softmax 최댓값, 0~1)
```

```python
# schemas/event.py
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field

class Event(BaseModel):
    """Neo4j 중심 노드(개념). 감성 count는 저장하지 않음(조회 시 집계)."""
    canonical_id: str | None = None        # 대표 식별자 UUID(신규 생성 전 None). 코드·문서 공통 용어
    canonical_title: str                   # 대표명. 감성 평가어 금지("실적 발표" O)
    importance: float | None = None        # TASK 06에서 계산
    companies: list[str] = Field(default_factory=list)  # PARTICIPATES_IN 대상
    created_at: datetime | None = None     # 이벤트 최초 생성 시각(관리·정렬 편의)

class MergeCandidate(BaseModel):
    event_id: str              # 후보 이벤트의 canonical_id(UUID)
    score: float               # 0.6·summary + 0.3·company + 0.1·time (event_merge.md §3)
    # 병합 품질 디버깅용 세부 점수(선택). 최종 score만으로는 어느 신호가 병합을 이끌었는지 알 수 없음.
    summary_similarity: float | None = None
    company_overlap: float | None = None
    time_similarity: float | None = None

class MergeDecision(BaseModel):
    """새 기사 병합 판정 결과."""
    assigned_event_id: str | None   # 편입될 이벤트의 canonical_id(UUID). None이면 신규 생성 대상
    is_new_event: bool
    best_score: float | None = None
    candidates: list[MergeCandidate] = Field(default_factory=list)
    # 확장 여지(지금은 넣지 않음): 향후 임베딩 병합 위에 LLM 검증 단계를 추가하면
    # llm_verified: bool 등을 여기에 덧붙인다. 현재 스키마는 이 확장을 막지 않도록 설계.

class CandidateEvent(BaseModel):
    """병합 후보 이벤트(조회 결과, TASK 05). RecentEventProvider가 반환, 점수 계산 입력."""
    canonical_id: str
    companies: list[str] = Field(default_factory=list)
    embedding: list[float]              # 대표 벡터(centroid). 계산·갱신은 backend, TASK 05는 읽기만
    event_time: datetime | None = None  # 이벤트 발생 시점(없으면 최신 기사 시각). time_proximity 입력

class EventArticleStats(BaseModel):
    """기존(저장된) 이벤트의 누적 기사 통계(TASK 06). 전체 재계산 시 이번 배치와 '합산'하는 입력."""
    article_count: int = 0
    publishers: list[str] = Field(default_factory=list)   # 원자료·distinct 계약(가중치는 agent가 적용)
    sentiment_magnitude_sum: float = 0.0                  # 감성 있는(None 아님) 저장 기사 강도 합
    sentiment_count: int = 0                              # 감성 있는 저장 기사 개수(평균 재결합용)
    updated_at: datetime | None = None                    # (선택) 통계 산출 시각. 디버깅용, 계산엔 미사용
```

```python
# schemas/report.py
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field

class SentimentGauge(BaseModel):
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    # 비율은 렌더러에서 계산하거나 property로 제공

class ArticleRef(BaseModel):
    """근거 기사 한 건. news_id·summary·url을 한 객체로 묶어 순서 어긋남/근거 추적 붕괴를 원천 차단."""
    news_id: int            # 근거 추적 키(= Article.id). evidence news_id 사슬(TASK 09 §0.2)의 원천
    summary: str
    url: str

class ReportEvent(BaseModel):
    canonical_title: str
    importance: float
    gauge: SentimentGauge
    article_count: int = 0   # 관련 기사 총 건수(실시간 집계). "관련 기사 42건" 표시용
    articles: list[ArticleRef] = Field(default_factory=list)  # 근거로 노출할 대표 소수(전체 아님)

class ReportModel(BaseModel):
    subject: str                       # 입력 종목/섹터
    generated_at: datetime
    overall_gauge: SentimentGauge
    top_events: list[ReportEvent] = Field(default_factory=list)
    data_limited: bool = False         # 데이터 부족 시 True("데이터 제한" 표기)
    note: str | None = None            # 제한 사유 등
```

```python
# schemas/response.py
from __future__ import annotations
from pydantic import BaseModel, Field
from schemas.event import Event
from schemas.report import ArticleRef, SentimentGauge

class EventWithArticles(BaseModel):
    event: Event
    article_count: int = 0   # 관련 기사 총 건수(실시간 집계). articles는 그 일부(대표 소수)
    # 화면 노출용 대표 소수(요약+링크 묶음, 순서 어긋남 방지). news_id를 이미 포함하므로
    # 일반 리포트는 이 대표 소수만으로 근거를 단다(재조회 불필요). 더 깊은 근거는 get_articles_by_event로 on-demand(TASK 09 §3.5).
    articles: list[ArticleRef] = Field(default_factory=list)
    gauge: SentimentGauge = Field(default_factory=SentimentGauge)  # 조회 시 실시간 집계 결과

class SubjectQueryResponse(BaseModel):
    """종목 조회 응답. importance 내림차순 정렬 가정."""
    subject: str
    # "없는 종목"과 "종목은 있으나 뉴스 0건"을 구분하기 위한 플래그.
    # 둘 다 events=[]가 되므로 리포트의 '데이터 제한' 문구를 다르게 쓰려면 필요.
    subject_found: bool = True
    events: list[EventWithArticles] = Field(default_factory=list)
    # 전체 감성 집계(None 제외). backend가 채운다 — ai는 재집계 안 함(절대규칙 4, SCHEMA_SPEC §7.3).
    overall_gauge: SentimentGauge = Field(default_factory=SentimentGauge)

class SaveResponse(BaseModel):
    ok: bool
    saved: int = 0
    message: str | None = None

class CleanupResponse(BaseModel):
    ok: bool
    deleted_articles: int = 0
    deleted_events: int = 0
    message: str | None = None
```

## 5. 규칙·제약 (CLAUDE.md)
- **§7 Pydantic v2 사용, 타입 힌트 필수.** `BaseModel` 상속, `Field(default_factory=...)`로 mutable 기본값 처리.
- **§2-3 LLM 출력은 반드시 Pydantic으로 파싱·검증.** `ExtractResult`가 그 계약이다.
- **§4 감성 판정을 스키마에서 문자열 자유입력으로 두지 않는다.** `Sentiment` Enum으로 제약.
- **§5 Event에 감성 count 저장 금지, canonical_title에 감성 평가어 금지.** 모델에 count 필드 없음 + docstring 규칙.
- **§2-5 환각 금지.** 리포트 모델에 `data_limited` 플래그로 데이터 부족을 명시적으로 표현.
- **§2-1 DB 직접 접근 금지.** 이 파일들은 요청/응답 명세일 뿐, ORM·SQL·드라이버 코드 없음.
- **§7 설정값 하드코딩 금지.** 스키마에는 임계값·가중치를 넣지 않는다(그 값들은 config.py, 계산은 TASK 05/06).

## 6. 완료 조건 (DoD)
- [ ] `schemas/article.py`, `event.py`, `report.py`, `response.py`, `__init__.py`가 위 시그니처대로 정의됨.
- [ ] 모든 모델이 Pydantic v2 `BaseModel` 기반이고 타입 힌트가 완전함.
- [ ] `Sentiment` Enum이 긍정/중립/부정 3종만 허용.
- [ ] `Event`에 감성 count류 필드가 없음(`created_at` 메타는 허용). `ExtractResult`에 감성/영향도 필드가 없음.
- [ ] `ExtractResult.events`가 **`EventCandidate`(title+confidence) 리스트**이고 `event_date`(datetime|None)가 있음. `EventCandidate.title`은 회사명·감성 평가어 없음.
- [ ] `SentimentResult`(TASK 04)·`CandidateEvent`(TASK 05)·`EventArticleStats`(TASK 06)가 `schemas`에 정의됨(services dataclass 아님). → 03/04/05/06은 별도 "TASK 01 동반 수정"이 불필요.
- [ ] 이벤트 대표 식별자는 `canonical_id: str`(UUID)로 통일, 이를 참조하는 `event_id`/`assigned_event_id`도 `str`. 안 쓰는 `Company` 모델을 정의하지 않음.
- [ ] `Article`에 `crawl_status`(pending/success/no_content/failed), `content_available`, `sentiment_score`, `analysis_completed`가 있고, `content_available`가 `crawl_status`와 정합됨.
- [ ] `ExtractResult.source_type`이 **`SourceType` Enum 3종**(article/rss_summary/title_only)임.
- [ ] 근거 기사는 `ArticleRef`(**news_id**+summary+url) 객체로 묶음. 요약/URL 병렬 리스트를 쓰지 않음. `ReportEvent`/`EventWithArticles`에 `article_count`(총 건수)가 `articles`(대표 소수)와 별도로 있음.
- [ ] `ReportModel`에 데이터 제한 표기 수단(`data_limited`)이, `SubjectQueryResponse`에 `subject_found`·**`overall_gauge`(backend 집계, ai 재집계 금지)**가 있음.
- [ ] `EventWithArticles.articles`(대표 소수, `ArticleRef`=news_id 포함)만으로 일반 리포트 근거가 닫힘. 추가 근거는 DTO에 싣지 않고 on-demand `get_articles_by_event`로 조회(TASK 08·09 §3.5).
- [ ] `python -c "import schemas"` (또는 동등) import 오류 없이 통과.
- [ ] `from schemas import Article, ExtractResult, Event, ReportModel, SubjectQueryResponse` 가 동작.

## 7. 테스트
- **대상**: 별도 전용 테스트 파일은 필수는 아니나, 최소한 다음을 확인.
  - 유효 데이터로 각 모델 인스턴스화가 성공.
  - `ExtractResult`가 누락 필드(예: summary 없음) 시 ValidationError를 던짐.
  - `Sentiment`에 허용 외 값 주입 시 ValidationError.
- **mock 전략**: 외부 호출 없음(순수 데이터 모델)이라 mock 불필요.
- **evals 연계**: 없음. (스키마는 tests 레벨에서만 검증. 품질 평가는 이후 축에서.)
- 후속 TASK(03 extract, 05 merge, 08 backend, 09 report)의 테스트가 이 스키마를 재사용하므로, 필드명이 바뀌면 여기부터 수정한다.

## 8. 구현 계약 요약 (I/O)
| 입력 | 출력 | 호출 가능 | 호출 금지 | 실패 시 |
|---|---|---|---|---|
| (없음, 순수 데이터 모델) | `schemas/*` Pydantic 모델(article·event·report·response·graph는 07) | — | DB·LLM·HTTP·계산 | ValidationError는 소비 TASK가 처리 |
