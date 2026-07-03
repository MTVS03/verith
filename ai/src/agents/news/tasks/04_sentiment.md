# TASK 04 — 감성분석 (services/finbert.py · nodes/sentiment.py)

## 0. 개요
- **목적**: 배치 흐름의 네 번째 단계. 추출 노드까지 지난 분석 대상 기사에 대해, **KR-FinBert-SC 전용 모델**로 기사별 감성(긍정/중립/부정)을 판정하고 그 confidence를 남긴다. 결과를 `Article.sentiment`(`Sentiment` Enum)와 `Article.sentiment_score`(0~1)에 채운다. **감성은 LLM에게 시키지 않는다**(CLAUDE.md §2-4). LLM은 추출만, 감성은 전용 모델이 담당한다.
- **선행 작업**: TASK 01(schemas: `Article.sentiment`/`sentiment_score`, `Sentiment` Enum), TASK 02(`crawl_status`/`content_available`, §4.1 본문 없는 기사 규칙), TASK 03(extract가 `content`·`crawl_status`·`content_available`를 갱신 — 감성 입력이 될 본문 확보 여부가 여기서 확정됨).
  - ⚠️ **TASK 01 동반 수정 필요**: 이 문서 §3.2·§4는 감성 결과 모델 `SentimentResult`를 **`services/`의 dataclass가 아니라 `schemas/`의 Pydantic 모델로 승격**할 것을 요구한다(`schemas/article.py`에 추가). 계약(schema)이므로 TASK 01부터 고치고 이 문서를 따른다.
- **산출물(파일)**:
  - `config.py`(발췌 추가) — 감성 모델 설정(모델명·디바이스·배치 크기·입력 상한·(원격 추론 시) 타임아웃·재시도·라벨 매핑). 하드코딩 금지의 귀착점.
  - `schemas/article.py`(발췌 추가 — ⚠️ TASK 01) — `SentimentResult` Pydantic 모델(`sentiment` + `score`=confidence). 감성 결과 계약을 schemas에 두어 서비스·노드·테스트가 같은 모델을 공유한다.
  - `services/finbert.py` — KR-FinBert-SC 클라이언트 + `classify()`/`classify_batch()` + 모델 라벨 → `Sentiment` Enum 매핑. 반환은 `schemas`의 `SentimentResult`. (무거운 로직은 여기, CLAUDE.md §2-2)
  - `nodes/sentiment.py` — 얇은 노드: 분석 대상 기사를 순회하며 본문(=`Article.content`, summary 아님)이 있는 기사만 `finbert`로 판정하고, 결과를 `Article`에 반영.
- **범위 밖(주의)**:
  - **감성 집계(게이지)는 저장하지 않는다.** Event에 감성 count를 저장하지 않고 조회 시 실시간 집계한다(CLAUDE.md §5, erd.dbml). 이 단계는 **기사별 판정**만 하고, 게이지 집계는 리포트 흐름(TASK 09)이 조회 시 수행한다.
  - **importance의 "감성 절대값" 계산은 TASK 06**. 여기서는 `sentiment_score`를 제공만 한다.
  - 임베딩·병합은 TASK 05, 저장은 TASK 08.
  - **감성을 LLM으로 판정하지 않는다**(CLAUDE.md §2-4). 이 문서 어디에도 LLM 감성 호출은 없다.

### 0.1 하위 의존성 (⚠️ 수정 시 영향 범위)
이 단계는 기사에 "감성"을 부여한다. 아래 계약을 바꾸면 후속 TASK가 영향받는다.

| 산출물 | 소비하는 TASK |
|---|---|
| 채워진 `Article.sentiment`(Enum 3종) | TASK 08(저장), 09(리포트 감성 게이지 실시간 집계) |
| 채워진 `Article.sentiment_score`(0~1 confidence) | TASK 06(importance의 "감성 절대값"), 09(리포트 표시) |
| "본문 없으면 감성 skip" 규칙(`crawl_status` 참조) | TASK 06(감성 없는 기사 처리), 09(게이지 집계 시 None 제외) |
| `SentimentResult`(schemas Pydantic 모델: sentiment+score) | 감성 서비스 반환 계약 — `nodes/sentiment.py`, 테스트가 공유. 필드 변경 시 TASK 01부터 수정 |
| `services/finbert.py`의 라벨 매핑 계약(모델 라벨 → 긍/중/부) | 내부 전용(다른 TASK가 라벨 문자열을 직접 다루지 않도록 이 파일에 격리) |

## 1. 참고 문서
- `docs/pipeline_spec.md` §2(배치 흐름에서 감성 위치), §3(모델 스택), §5(감성분석: KR-FinBert-SC로 기사별 긍/중/부), §9(importance에 감성 절대값).
- `docs/model_choice.md` §2(감성: KR-FinBert-SC, 왜 이 모델·왜 LLM 안 씀), §4(모델 분업).
- `docs/sequence.md` §1(배치 시퀀스: extract 다음 `finbert.py` 감성).
- `docs/erd.dbml` — news 테이블 `sentiment`(긍정/중립/부정), Neo4j 주석(감성 count 저장 안 함 → 조회 시 실시간 집계).
- `CLAUDE.md` §2-1(DB 직접 접근 금지), §2-2(nodes 얇게), §2-4(감성은 LLM 금지·전용 모델), §2-5(환각 금지), §4(모델 스택: KR-FinBert-SC / services/finbert.py), §5(감성 count 미저장·실시간 집계), §7(코딩 컨벤션: 타임아웃·재시도·예외 로깅·skip·하드코딩 금지).
- TASK 01 `schemas/article.py` — `Sentiment` Enum(긍정/중립/부정), `Article.sentiment`, `Article.sentiment_score`.
- TASK 02 §4.1(본문 없는 기사 규칙: `no_content` 시 감성 skip), §4 `CrawlStatus` 상태 매핑.

## 2. 배경 (왜)
- **왜 전용 모델(KR-FinBert-SC)인가**: 감성을 LLM에 맡기면 부정확·환각이 생기고 LLM 부담도 커진다. KR-FinBert-SC는 한국어 + 금융 도메인 특화(서울대 NLP랩)라 "어닝쇼크"·"실적 부진" 같은 금융 표현을 정확히 잡는다. 각 모델이 잘하는 것만 시킨다 (model_choice §2/§4, CLAUDE.md §2-4).
- **왜 기사 본문 전체를 입력으로 쓰나**: 제목만으로는 감성 방향이 안 잡힌다. "실적 발표" 같은 중립 제목은 본문을 봐야 호조/부진이 갈린다 (pipeline_spec §4). 그래서 감성 입력은 `Article.content`(추출 단계에서 확보된 순수 텍스트 본문)다.
- **왜 `summary`가 아니라 `content`인가(중요)**: `summary`(LLM 통일 요약)는 **이벤트 병합**(TASK 05, event_merge.md §2)의 입력이지 감성의 입력이 아니다. 요약은 사실을 압축하며 감성 신호(어조·강조·부정 표현)를 깎아낼 수 있어, 요약으로 감성을 판정하면 방향·세기가 약해진다. 감성은 반드시 **원문 본문(`Article.content`)**을 KR-FinBert에 넣는다. 두 모델이 서로 다른 입력을 쓴다는 점을 혼동하지 않는다(감성=content, 병합=summary 임베딩).
- **왜 본문이 없으면 감성을 skip하나**: 본문 없는 속보(`no_content`)를 제목만으로 감성 추론하면 환각이다(CLAUDE.md §2-5). `content=None`인 기사는 감성 판정을 **수행하지 않고** `sentiment=None`으로 남긴다. 그래서 `crawl_status`를 반드시 참조해 분기한다 (TASK 02 §4.1: "본문이 없으면 감성 분석을 수행하지 않거나 정책에 따라 Skip").
- **왜 `sentiment_score`(confidence)를 남기나**: importance(TASK 06)의 "감성 절대값" 신호와 리포트 표시에 쓰인다. 감성 라벨(긍/중/부)만으로는 세기를 알 수 없으므로 모델이 준 예측 confidence(0~1)를 함께 보관한다 (TASK 01 §3.1, pipeline_spec §9).
- **왜 감성 게이지를 여기서 집계·저장하지 않나**: Event에 감성 count를 저장하지 않고 조회 시 실시간 집계한다(CLAUDE.md §5). 이 단계는 기사 1건의 라벨만 확정하고, 분포(긍/중/부 건수)는 리포트 흐름(TASK 09)이 조회 시 만든다. 여기서 집계값을 만들어 두면 이중 소스가 되어 정합이 깨진다.
- **왜 로직은 `finbert.py`, 노드는 얇게**: 모델 로드·추론·라벨 매핑 같은 무거운 로직은 `services/`에 둔다. `nodes/sentiment.py`는 순회·반영만 하는 얇은 껍데기다 (CLAUDE.md §2-2).
- **왜 라벨 매핑을 config/서비스에 격리하나**: 모델이 내보내는 라벨명(`LABEL_0` / `positive` 등)은 모델 카드에 종속된다. 이를 `Sentiment` Enum(긍정/중립/부정)으로 바꾸는 매핑을 한 곳에 모아, 모델 교체 시 그 지점만 고치도록 한다. 라벨 문자열을 파이프라인 여기저기서 다루지 않는다.
- **DB 접근 금지**: 감성 판정은 로컬 모델 추론만 한다. 저장은 TASK 08에서 backend HTTP로만 한다 (CLAUDE.md §2-1).

## 3. 요구사항

### 3.1 `config.py` — 감성 모델 설정 (하드코딩 금지)
1. **모델·디바이스**: `FINBERT_MODEL`(KR-FinBert-SC 식별자), `FINBERT_DEVICE`(`"cpu"`/`"cuda"`). model_choice §2의 모델로 통일한다. 목업·일반 한국어 감성 모델로 바꾸지 않는다 (CLAUDE.md §4).
2. **배치·입력 상한**: `FINBERT_BATCH_SIZE`(배치 추론 크기 — 400건/시간 처리량 확보용, 튜닝 대상), `FINBERT_MAX_INPUT_CHARS`(BERT 계열의 512 토큰 한계를 고려한 입력 상한). 상한 초과 본문은 잘라 입력한다(속도·토큰 한계).
3. **외부 호출 안전장치**(원격 추론 서버를 쓰는 경우): `FINBERT_TIMEOUT`, `FINBERT_MAX_RETRIES`, `FINBERT_RETRY_BACKOFF`. 외부 호출은 타임아웃·재시도를 둔다 (CLAUDE.md §7). 로컬 in-process 로드만 쓰면 타임아웃은 무의미하지만, 계약을 흔들지 않도록 값은 정의해 둔다.
4. **라벨 매핑**: `FINBERT_LABEL_MAP` — 모델 출력 라벨명 → `Sentiment` 값(긍정/중립/부정) 매핑. 실제 라벨명은 모델 카드 확인 후 확정한다(주석으로 튜닝/확인 대상 표기). 하드코딩 금지 원칙에 따라 코드가 아니라 config에서 읽는다 (CLAUDE.md §7).

### 3.2 `services/finbert.py` — KR-FinBert 감성 서비스
1. **모델 로드**: `config`의 `FINBERT_MODEL`/`FINBERT_DEVICE`로 KR-FinBert-SC를 로드한다. 모델은 무겁고 재사용되므로 **지연 로드 + 프로세스 내 1회 로드(싱글턴/모듈 캐시)**로 두어 기사마다 다시 로드하지 않는다(속도).
2. **`classify(text)`**: 기사 **본문**(`Article.content`, summary 아님) 텍스트 1건 → **`schemas`의 `SentimentResult`(sentiment: `Sentiment`, score: float 0~1)** 반환. 반환 타입은 이 서비스가 정의한 dataclass가 아니라 **`schemas/article.py`의 Pydantic 모델**이다(§0 ⚠️ TASK 01 승격).
   - 입력은 `FINBERT_MAX_INPUT_CHARS`로 잘라 넣는다(512 토큰 한계).
   - 모델 출력 라벨을 `FINBERT_LABEL_MAP`으로 `Sentiment` Enum(긍정/중립/부정)에 매핑한다. **`score`는 곧 `Article.sentiment_score`이며, 예측 라벨의 confidence(softmax 최댓값, 0~1)다**(다른 값 아님 — TASK 01 `sentiment_score` 계약, importance·리포트가 이 confidence를 소비).
   - 매핑에 없는 라벨이 나오면 예외를 삼키지 말고 로깅하고, 해당 기사는 감성 실패로 신호한다(파이프라인은 계속 — CLAUDE.md §7). 임의로 "중립"으로 눕히지 않는다(오분류 은폐 방지).
3. **`classify_batch(texts)`**: 여러 기사 본문을 **배치 추론**해 `list[SentimentResult]`로 반환한다(400건/시간 처리량, model_choice §1 "배치 처리로 최적화"). 순서는 입력 순서와 일치시킨다(호출측이 기사와 인덱스로 짝지음).
   - **배치 실패 시 개별 fallback**: 배치 추론이 실패하면(예: OOM·특정 입력에서 예외) 배치 전체를 버리지 말고 **각 텍스트를 `classify()`로 1건씩 재시도**한다. 이때 개별 실패한 기사만 감성 실패(그 자리 `None` 상당)로 신호하고 나머지는 정상 결과를 채운다. 한 건의 이상 입력이 배치 전체의 감성을 날리지 않도록 하기 위함이다(실패 격리, CLAUDE.md §7). 반환 리스트 길이·순서는 입력과 항상 일치시킨다.
4. **본문 없는 입력을 감성 추론하지 않는다**: 빈 문자열·`None`을 받으면 모델을 호출하지 않고 "감성 없음"을 신호한다(환각 금지, CLAUDE.md §2-5). 본문 유무 판단(=`crawl_status` 참조)은 호출측(노드)이 하지만, 서비스도 빈 입력을 방어적으로 거른다.
5. **부수효과 최소화**: `classify`는 입력 텍스트 → 출력(라벨+score)에 가깝게. 저장·DB 접근 없음 (CLAUDE.md §2-1). `Article` 갱신은 노드가 한다.
6. **감성 외 판단을 하지 않는다**: 이 서비스는 감성만 낸다. importance·요약·개체 등 다른 판단을 여기 섞지 않는다(단일 책임, CLAUDE.md §7).

### 3.3 `nodes/sentiment.py` — 감성 노드 (얇게)
1. `state["articles"]`(추출 노드까지 지난 `Article` 리스트)를 순회하며, **본문이 있는 기사만** 감성 판정 대상으로 고른다. 노드는 순서만 담당하는 얇은 껍데기 (CLAUDE.md §2-2).
2. **본문 유무 분기 규칙**(TASK 02 §4.1과 정합):
   | `crawl_status` | 처리 |
   |---|---|
   | `success` (본문 있음, `content_available=True`) | `Article.content`로 감성 판정 → `sentiment`·`sentiment_score` 채움 |
   | `no_content` (속보/본문 없음) | 감성 판정 **skip**. `sentiment=None`, `sentiment_score=None` 유지(제목만으로 추론 안 함) |
   | `failed` (크롤링 실패) | 감성 판정 skip(파이프라인 계속) |
3. **결과 반영**: 판정한 기사에 `Article.sentiment`(Enum)와 `Article.sentiment_score`(0~1)를 세팅한다. `crawl_status`/`content_available`는 이 단계에서 바꾸지 않는다(감성은 상태를 소비만 함).
4. **배치 활용**: 본문 있는 기사들을 모아 `finbert.classify_batch`로 한 번에 처리하고, 결과를 원래 기사와 순서로 짝지어 반영한다(처리량). 소량이거나 단순 구현이면 `classify`를 개별 호출해도 되지만 계약(순서 일치)은 지킨다.
5. **실패 격리**: 한 기사의 감성 판정이 실패해도 예외로 파이프라인을 죽이지 않는다. 실패 기사는 로깅 후 `sentiment=None`으로 두고 나머지는 계속한다 (CLAUDE.md §7).
6. **모델을 직접 로드하지 않는다**: 노드는 `services/finbert.py`만 호출한다. transformers·토크나이저 등 모델 로직을 노드에 두지 않는다 (CLAUDE.md §2-2).
7. 분석 대상 0건이거나 본문 있는 기사가 하나도 없으면 예외 없이 그대로 넘긴다(환각 금지: 없으면 없는 대로 — CLAUDE.md §2-5). 후속·리포트가 "데이터 제한"으로 처리한다.

## 4. 인터페이스 / 구현 규칙

> 아래는 확정 시그니처(초안). 함수명·반환 타입은 이대로 구현하되, 설정값은 `config.py`에서 읽는다. 함수 본문(로직)은 비워 둔다.

```python
# config.py (발췌) — 감성 모델 설정. 값은 실데이터/모델카드 확인 대상(주석 표기).
FINBERT_MODEL: str = "snunlp/KR-FinBert-SC"   # 한국어 금융 감성(서울대 NLP). 일반 감성 모델로 대체 금지
FINBERT_DEVICE: str = "cpu"                    # 가능 시 "cuda"
FINBERT_BATCH_SIZE: int = 16                   # 배치 추론 크기(처리량) — 튜닝 대상
FINBERT_MAX_INPUT_CHARS: int = 2000            # 입력 상한(BERT 512토큰 고려). 초과분은 잘라 입력 — 튜닝 대상
FINBERT_TIMEOUT: float = 30.0                  # (원격 추론 서버 사용 시) 타임아웃(초)
FINBERT_MAX_RETRIES: int = 2                   # (원격) 재시도 횟수
FINBERT_RETRY_BACKOFF: float = 1.0             # (원격) 재시도 간 대기(초)
# 모델 출력 라벨 → Sentiment 값 매핑. 실제 라벨명은 모델 카드 확인 후 확정(예시값).
FINBERT_LABEL_MAP: dict[str, str] = {
    "positive": "긍정",
    "neutral":  "중립",
    "negative": "부정",
}
```

```python
# schemas/article.py (발췌 — ⚠️ TASK 01에서 확정할 스키마 승격. 여기서는 계약만 표시)
from __future__ import annotations
from pydantic import BaseModel

class SentimentResult(BaseModel):
    """감성 판정 결과. services가 아닌 schemas에 두어 서비스·노드·테스트가 공유."""
    sentiment: Sentiment   # 긍정 | 중립 | 부정 (모델 라벨 → FINBERT_LABEL_MAP으로 매핑)
    score: float           # = Article.sentiment_score. 예측 라벨 confidence(softmax 최댓값, 0~1)
```

```python
# services/finbert.py — KR-FinBert-SC 감성 서비스
# ⚠️ 감성은 이 서비스에서만 판정한다. LLM(services/llm.py)에게 감성을 시키지 않는다(CLAUDE.md §2-4).
# ⚠️ 반환 SentimentResult는 schemas 소유(여기서 재정의하지 않는다).
from __future__ import annotations
from schemas.article import SentimentResult   # dataclass가 아니라 schemas Pydantic 모델

def classify(text: str) -> SentimentResult:
    """기사 본문(Article.content, summary 아님) 1건 → 감성 라벨 + confidence.
    - 입력은 FINBERT_MAX_INPUT_CHARS로 잘라 넣는다(512 토큰 한계).
    - 모델 라벨을 FINBERT_LABEL_MAP으로 Sentiment Enum에 매핑. 매핑 밖 라벨은 로깅 후 실패 신호(중립 강제 금지).
    - score = 예측 라벨 confidence(0~1) = Article.sentiment_score.
    - 빈 문자열/None은 모델 호출 없이 감성 없음 신호(환각 금지). 저장·부수효과 없음.
    """
    ...

def classify_batch(texts: list[str]) -> list[SentimentResult]:
    """여러 기사 본문 배치 추론(처리량). 반환 길이·순서는 입력과 항상 일치.
    - 배치 추론 실패 시 각 텍스트를 classify()로 1건씩 fallback 재시도(실패 격리).
      개별 실패한 기사만 감성 실패로 신호, 나머지는 정상 결과.
    - 본문 없는 기사는 애초에 호출측에서 제외하고 넘긴다.
    """
    ...
```

```python
# nodes/sentiment.py — 얇은 감성 노드
# ⚠️ 모델을 직접 로드하지 않는다(transformers/토크나이저는 services/finbert.py에).
from __future__ import annotations
import services.finbert as finbert

def sentiment_node(state: dict) -> dict:
    """state["articles"]를 순회하며 본문 있는 기사만 감성 판정.
    - crawl_status == "success" 인 기사만 대상. content로 finbert 판정.
    - Article.sentiment / sentiment_score 갱신. no_content/failed는 skip(None 유지, 제목 추론 금지).
    - 본문 있는 기사들을 모아 classify_batch로 처리하고 순서로 짝지어 반영(처리량).
    - 한 기사 실패해도 로깅 후 skip, 파이프라인은 계속.
    """
    ...
```

### 4.1 감성 skip 규칙 (환각 금지)
본문 없이 제목만으로 감성을 추론하지 않는다(CLAUDE.md §2-5, TASK 02 §4.1). `crawl_status`에 따라 다음과 같이 처리한다.

| 상황 | content | 감성 처리 | 결과 필드 |
|---|---|---|---|
| 본문 존재(`success`) | 순수 텍스트 | KR-FinBert 판정 | `sentiment`=긍/중/부, `sentiment_score`=confidence |
| 속보/본문 없음(`no_content`) | `None` | **skip**(제목 추론 금지) | `sentiment=None`, `sentiment_score=None` |
| 크롤링 실패(`failed`) | `None` | skip(파이프라인 계속) | `sentiment=None`, `sentiment_score=None` |

- `sentiment=None`은 "감성을 붙일 수 없었음"을 뜻한다. 후속(TASK 06 importance, TASK 09 게이지 집계)은 `None`을 **집계에서 제외**한다(강제로 중립으로 세지 않는다).
- 감성 게이지(긍/중/부 건수)는 이 단계에서 만들지 않는다. 조회 시 실시간 집계다(CLAUDE.md §5).

## 5. 규칙·제약 (CLAUDE.md)
- **§2-4 감성 판정·점수는 LLM에게 시키지 않는다.** 감성은 오직 `services/finbert.py`(KR-FinBert-SC)가 낸다. 이 단계 어디에도 LLM 감성 호출이 없다.
- **§2-2 nodes는 얇게, 로직은 services.** 모델 로드·추론·라벨 매핑은 `services/finbert.py`. `nodes/sentiment.py`는 순회·분기·반영만.
- **§2-5 환각 금지.** 본문 없으면 제목으로 지어내지 않고 `sentiment=None`으로 skip. 매핑 밖 라벨을 임의로 중립 처리하지 않는다.
- **§5 Event 감성 count 저장 금지, 조회 시 실시간 집계.** 이 단계는 기사별 라벨만 확정하고 게이지를 만들지 않는다.
- **§2-1 DB 직접 접근 금지.** 로컬 모델 추론만. 저장은 TASK 08(backend HTTP).
- **§4 모델 스택 고정.** 감성은 KR-FinBert-SC / services/finbert.py. 다른 감성 모델로 임의 대체 금지.
- **§7 외부 호출은 타임아웃·재시도, 예외는 로깅, 실패는 skip하되 파이프라인 계속.** (원격 추론 서버 사용 시 적용)
- **§7 설정값 하드코딩 금지.** 모델명·디바이스·배치 크기·입력 상한·라벨 매핑은 `config.py`에서 읽는다.

## 6. 완료 조건 (DoD)
- [ ] `config.py`에 `FINBERT_MODEL`(KR-FinBert-SC)/`FINBERT_DEVICE`/`FINBERT_BATCH_SIZE`/`FINBERT_MAX_INPUT_CHARS`/`FINBERT_TIMEOUT`/`FINBERT_MAX_RETRIES`/`FINBERT_RETRY_BACKOFF`/`FINBERT_LABEL_MAP`이 정의됨. 일반 한국어 감성 모델·목업 표기 없음.
- [ ] **`SentimentResult`가 `schemas/article.py`의 Pydantic 모델로 승격됨**(services의 dataclass 아님). `services/finbert.py`는 이를 재정의하지 않고 `schemas`에서 import함. ⚠️ 이 스키마 승격이 TASK 01에 반영됨.
- [ ] `services/finbert.py`의 `classify(text)`가 `SentimentResult`(sentiment: `Sentiment`, score: 0~1)를 반환함. 라벨은 `FINBERT_LABEL_MAP`으로 `Sentiment` Enum(긍정/중립/부정)에 매핑되고, **`score`가 예측 라벨 confidence(= `Article.sentiment_score`)임이 명시됨**.
- [ ] 감성 입력이 **`Article.content`(본문)이고 `summary`가 아님**이 서비스·노드·문서에 명확함.
- [ ] 입력이 `FINBERT_MAX_INPUT_CHARS`로 잘려 들어가고(512 토큰 한계), 빈/None 입력은 모델 호출 없이 감성 없음으로 처리됨.
- [ ] 매핑 밖 라벨이 나오면 로깅 후 실패 신호(임의 중립 강제 없음).
- [ ] `classify_batch(texts)`가 배치 추론하고 **입력 순서·길이와 결과가 일치**하며, **배치 실패 시 개별 `classify()` fallback**으로 실패를 건 단위로 격리함.
- [ ] **감성 판정에 LLM을 사용하지 않음**(services/llm.py 미호출). 감성은 KR-FinBert-SC만 판정.
- [ ] `nodes/sentiment.py`가 `services/finbert.py`만 호출하고 모델을 직접 로드하지 않음.
- [ ] `crawl_status == "success"`(본문 있음) 기사만 감성 판정, `no_content`/`failed`는 skip하여 `sentiment=None`·`sentiment_score=None` 유지(제목 추론 없음) — §4.1 표대로.
- [ ] 판정된 기사에 `Article.sentiment`(Enum 3종)와 `Article.sentiment_score`(0~1)가 채워짐. `crawl_status`/`content_available`는 이 단계에서 변경하지 않음.
- [ ] 감성 게이지(긍/중/부 건수)를 이 단계에서 집계·저장하지 않음(조회 시 실시간 집계).
- [ ] 한 기사 실패 시 로깅 후 skip, 나머지는 계속. 분석 대상 0건·본문 있는 기사 0건일 때 예외 없이 통과.

## 7. 테스트
- **대상 파일**: `tests/test_sentiment.py`(존재).
- **mock 전략**: 실제 모델·네트워크를 호출하지 않는다 (CLAUDE.md: tests는 mock 기반). KR-FinBert 추론(transformers pipeline 또는 원격 호출)을 mock해 고정 라벨·확률을 돌려준다.
  - `classify`: mock이 `positive`/`neutral`/`negative`(+확률)를 줄 때 `FINBERT_LABEL_MAP`을 거쳐 `Sentiment.POSITIVE/NEUTRAL/NEGATIVE`와 올바른 `score`(0~1)로 매핑되는지.
  - **입력 상한**: `FINBERT_MAX_INPUT_CHARS`를 넘는 본문이 잘려 입력되는지(초과분 truncation).
  - **빈/None 입력**: 모델을 호출하지 않고 감성 없음으로 처리되는지(환각 금지).
  - **매핑 밖 라벨**: 예상 밖 라벨(mock)에서 로깅·실패 신호가 나오고 임의 중립 강제가 없는지.
  - `classify_batch`: 여러 입력의 결과 순서가 입력 순서와 일치하는지.
  - `sentiment_node`: (1) `crawl_status="success"` 기사는 `sentiment`/`sentiment_score`가 채워지는지, (2) `no_content`/`failed` 기사는 `sentiment=None`으로 skip되는지, (3) 한 기사 판정 실패 시 나머지가 계속 처리되는지, (4) 본문 있는 기사 0건일 때 예외 없이 통과하는지.
  - **감성은 LLM 미사용**: 노드/서비스가 `services/llm.py`를 호출하지 않음을 확인(감성 판정 경로에 LLM 부재).
- **경계 케이스**: 본문 길이 = `FINBERT_MAX_INPUT_CHARS` 경계, 전 기사 `no_content`(전부 skip → 감성 0건), confidence 경계값(0.0/1.0).
- **evals 연계**: 감성 품질(정답 대비 정확도·F1)은 이후 `evals/` 축에서 정답셋 대조로 다룬다(모델 없이 결정적 채점, model_choice §5). 여기서는 tests 레벨(매핑·분기·계약) 검증.
- 후속 TASK(06 importance의 감성 절대값, 09 리포트 게이지)가 `Article.sentiment`/`sentiment_score`를 재사용하므로, 필드 의미(Enum 3종·None=skip)를 바꾸면 TASK 01부터 함께 수정한다.
