# TASK 06 — 중요도(importance) 계산 (services/importance.py · nodes/importance.py)

## 0. 개요
- **목적**: 배치 흐름의 일곱 번째 단계. 병합(TASK 05)으로 각 기사에 `Article.event_id`가 배정되고 이벤트 골격이 만들어진 뒤, **이벤트마다 중요도 점수 `Event.importance`를 객관 신호로 계산**한다. 공식은 pipeline_spec §9 / erd.dbml 그대로 **`importance = 기사 개수 + 언론사 가중치 + 감성 절대값`** 이며, 세 신호를 config 가중치로 결합한 **결정적(deterministic) 계산**이다. 이 점수는 그래프(TASK 07)·저장(TASK 08)을 거쳐 리포트(TASK 09)에서 **최신순이 아니라 중요도순 정렬·TOP 선정**의 기준이 된다. **importance는 LLM이 지어내지 않는다**(CLAUDE.md §2-4/§2-5, pipeline_spec §9: "LLM이 지어내는 값이 아니라 객관 신호로 계산").
- **선행 작업**:
  - TASK 01(schemas: `Event.importance`(`float | None`), `Article.publisher`·`Article.sentiment`(`Sentiment` Enum)·`Article.sentiment_score`·`Article.event_id`).
  - TASK 04(`Article.sentiment`/`sentiment_score` 채움. **본문 없으면 `sentiment=None` → 집계 제외** 규칙, §4.1).
  - TASK 05(`Article.event_id` 배정 + 이번 배치 `Event`를 `state["events_by_id"]`에 등록. importance는 여기서 만든 이벤트에 점수를 부여).
  - ✅ **TASK 01에 반영됨**: **기존 이벤트의 누적 기사 통계** `EventArticleStats`는 이제 TASK 01 `schemas/event.py`에 정의되어 있다(서비스·백엔드 클라이언트·테스트가 같은 계약 공유). 이 문서는 그 계약을 소비한다(별도 동반 수정 불필요). (`Event.importance` 필드도 TASK 01에 이미 존재.)
- **산출물(파일)**:
  - `config.py`(발췌 추가) — importance 설정(세 신호 가중치 + **언론사 가중치 테이블**(⚠️ 미확정, CLAUDE.md §8) + 미등록 언론사 기본값 + 기사 수 감쇠 옵션). 하드코딩 금지의 귀착점.
  - `schemas/event.py`(발췌 추가 — ⚠️ TASK 01) — `EventArticleStats`(기존 이벤트의 누적 통계: article_count·publishers·감성 강도 합). 전체 재계산의 조회 계약.
  - `services/importance.py` — 순수 계산: `publisher_weight()`/`sentiment_magnitude()`/`compute_importance()` + 기존 통계 조회 인터페이스(`EventArticleStatsProvider` Protocol). LLM·DB 없음.
  - `nodes/importance.py` — 얇은 노드: 이번 배치에서 `event_id`가 배정된 기사를 이벤트별로 묶어 `compute_importance`를 호출하고, 신규 이벤트는 `Event.importance`에, 모든 영향 이벤트는 `state["importance_by_event_id"]`에 반영.
- **범위 밖(주의)**:
  - **감성 판정 자체는 TASK 04**. 여기서는 이미 채워진 `Article.sentiment`/`sentiment_score`를 **소비만** 한다(감성을 다시 판정하지 않는다).
  - **이벤트 배정·canonical 생성은 TASK 05**. 여기서는 `Article.event_id`·`Event`를 읽어 점수만 부여한다(병합하지 않는다).
  - **감성 게이지(긍/중/부 분포)를 집계·저장하지 않는다.** importance는 **정렬용 스칼라 하나**일 뿐, 분포는 Event에 저장하지 않고 조회 시 실시간 집계(TASK 09) — erd.dbml/CLAUDE.md §5. 여기서 분포를 만들어 두면 이중 소스가 된다.
  - **기존 이벤트의 누적 기사 실제 조회(Neo4j/PostgreSQL)는 TASK 08**. 여기서는 `EventArticleStatsProvider` **인터페이스(계약)만** 정의하고, 실제 backend HTTP 조회 구현은 TASK 08이 채운다(절대규칙 1: DB 직접 접근 금지). TASK 06은 주입된 provider를 소비만 한다.
  - **Neo4j 노드·관계 구성은 TASK 07**, **저장은 TASK 08**. importance는 Event 속성으로 저장되지만 저장 행위 자체는 TASK 08이다.
  - **언론사 가중치 테이블의 실제 값 확정은 실데이터 튜닝(⚠️ 미확정, CLAUDE.md §8)**. 여기서는 임시값 + 조회 규칙만 둔다.
  - **cleanup(7일 롤링) 이후 importance 재계산은 backend 소유**. 이 단계는 배치에서 새 기사가 편입된 이벤트만 계산한다. 삭제로만 기사가 준 이벤트의 stale importance 갱신 정책은 §4.2·SCHEMA_SPEC §5 참고(공식은 §3.2와 공유).

### 0.1 하위 의존성 (⚠️ 수정 시 영향 범위)
이 단계는 이벤트에 "중요도"를 부여한다. 아래 계약을 바꾸면 후속 TASK가 영향받는다.

| 산출물 | 소비하는 TASK |
|---|---|
| 채워진 `Event.importance`(객관 계산 스칼라) | TASK 07(그래프: Event 속성), 08(저장), 09(리포트 TOP 선정·중요도순 정렬, 질의 잠정 랭킹 = importance순) |
| `state["importance_by_event_id"]`(event_id → score) | TASK 08(저장: **편입(기존) 이벤트에도** importance 반영) |
| importance 공식·가중치·언론사 테이블(config) | evals(중요도 품질), 실데이터 튜닝 |
| `EventArticleStatsProvider` 인터페이스 + `EventArticleStats` | TASK 08(backend 클라이언트가 이 인터페이스를 구현해 실제 조회). 필드 변경 시 TASK 01부터 |

## 1. 참고 문서
- `docs/pipeline_spec.md` §9(importance = 기사 개수 + 언론사 가중치 + 감성 절대값, LLM 생성 아님·객관 계산), §8(Event에 importance 보관 → 최신순 아닌 중요도순 정렬), §11(질의 관련도 잠정 = importance순), §10(7일 롤링으로 기사 집합이 변함).
- `docs/erd.dbml` — Neo4j Event(`importance`), `_import_note`(importance 공식 + 감성 count는 저장 안 하고 조회 시 실시간 집계).
- `docs/event_merge.md` §7(증분편입: 기존 이벤트에 새 기사가 편입되므로 이벤트의 기사 집합이 배치마다 변함 → 재계산 필요).
- `docs/sequence.md` §1(배치 시퀀스: event_merge → `importance.py` 중요도 → save).
- `CLAUDE.md` §2-1(DB 직접 접근 금지), §2-2(nodes 얇게·로직은 services), §2-4(감성·점수는 전용 모델·계산이지 LLM 아님 → importance도 LLM 금지), §2-5(환각 금지: 없는 신호를 지어내지 않음), §5(감성 count 미저장·조회 시 집계·7일 롤링), §7(코딩 컨벤션: 예외 로깅·skip·설정값 하드코딩 금지), §8(미확정: **importance 언론사 가중치 테이블 미정**).
- TASK 01 `schemas/event.py`(`Event.importance`), `schemas/article.py`(`Article.publisher`·`Sentiment`·`sentiment`·`sentiment_score`·`event_id`).
- TASK 04 §4.1(감성 skip 규칙: `sentiment=None`은 집계에서 제외, 강제 중립 금지).
- TASK 05 §3.6(`Article.event_id` 배정 + `state["events_by_id"]` 등록 + 편입 이벤트 참조 기록).

## 2. 배경 (왜)
- **왜 LLM이 아니라 객관 계산인가**: 중요도를 LLM에 물으면 근거 없는 수치·환각이 생기고 재현성이 없다. importance는 **관측 가능한 객관 신호**(기사 수·언론사·감성 세기)의 결정적 함수로 계산해 "왜 이 점수인지"를 설명할 수 있게 한다 (pipeline_spec §9, CLAUDE.md §2-4/§2-5). 이 단계 어디에도 LLM 호출이 없다.
- **왜 세 신호인가(각자 다른 측면)**:
  - **기사 개수(노출량)**: 많은 매체·기사가 다룰수록 시장이 주목하는 사건이다.
  - **언론사 가중치(출처)**: 같은 1건이라도 어느 매체가 다뤘는지에 따라 신뢰·도달이 다르다. 주요 경제지·종합지에 가중을 준다.
  - **감성 절대값(사건 강도)**: 강한 호재도 강한 악재도 "중요한" 사건이다. 방향이 아니라 **세기**가 중요도 신호다.
  - 세 신호는 상관이 있으나(많이 다뤄진 사건은 대개 강한 감성) 서로 다른 축을 잡는다. 계수로 결합하며 계수는 실데이터 튜닝이다.
- **왜 감성 "절대값"인가(방향이 아니라 세기)**: importance는 "좋다/나쁘다"가 아니라 "중요하다/아니다"를 잰다. 강한 긍정(+)과 강한 부정(−) 모두 중요도를 올리고, **중립은 강도 0으로 기여가 낮다**. 그래서 감성의 **부호가 아니라 크기**만 쓴다. (병합(TASK 05)이 감성을 **아예 안 쓰는 것**과는 다른 규칙이다 — importance는 감성의 세기를 쓰되 방향은 버린다.)
- **왜 `sentiment=None`은 집계에서 제외하나**: 본문 없는 속보 등은 감성을 붙일 수 없어 `sentiment=None`이다(TASK 04 §4.1). 이를 억지로 "중립 0"으로 세면 감성 신호가 왜곡된다. **None은 감성 항의 분모에서 제외**하고, 감성 있는 기사가 하나도 없으면 감성 항은 0으로 둔다(없는 걸 지어내지 않음, 환각 금지 CLAUDE.md §2-5). (반면 **중립(긍/부 아님)은 강도 0으로 분모에 포함**된다 — 중립 일색 커버리지는 강도가 낮다는 뜻을 정확히 표현.)
- **왜 기사 수에 감쇠(log)를 두고, 왜 bool이 아니라 모드 문자열인가**: 같은 사건의 근접 중복 기사가 쏟아지면 기사 수만으로 한 이벤트가 순위를 독점한다. `log1p` 같은 체감(diminishing) 변환으로 "10건→100건"의 차이가 "1건→10건"보다 완만하게 반영되게 한다. 다만 `log1p`/`sqrt`/`linear` 중 무엇이 실데이터에서 맞는지는 실험 대상이므로, `True/False` 토글이 아니라 **`IMPORTANCE_VOLUME_MODE` 문자열**로 두어 변환 함수를 값 하나로 갈아끼운다(확장성).
- **왜 Event에 importance는 저장하되 감성 count는 저장 안 하나**: importance는 **정렬 키인 파생 스칼라 하나**라 저장해 두면 조회·정렬이 싸다. 반면 감성 **분포(긍/중/부 건수)**는 저장하지 않고 조회 시 실시간 집계한다(하루 수백 건 수준, erd.dbml/CLAUDE.md §5). 그래서 이 단계는 스칼라 하나만 만들고 분포는 만들지 않는다.
- **importance는 Neo4j Event의 property로도 쓰인다**: 배치 흐름은 importance → graph(TASK 07) → save(TASK 08)로 이어지며, TASK 07이 Event 노드를 구성할 때 **importance를 Event property로 저장**한다(erd.dbml Neo4j Event: `importance`). 그래서 이 값은 질의 흐름에서 Neo4j를 importance순으로 정렬·TOP 선정하는 데 그대로 쓰인다(pipeline_spec §8/§11). 즉 여기서 만든 스칼라 하나가 그래프의 정렬 축이 된다.
- **왜 전체 기사 집합으로 재계산이 필요하고, 왜 그 조회를 인터페이스로만 두나**: 증분편입(event_merge §7)과 7일 롤링 삭제(pipeline_spec §10)로 한 이벤트의 기사 집합은 배치마다 바뀐다. importance는 **현재 이벤트의 전체 기사**를 반영한 스냅샷이어야 순위가 맞다. 그런데 기존(이미 저장된) 기사의 통계는 DB에 있고 이는 backend HTTP로만 접근한다(절대규칙 1). 그래서 TASK 06은 `EventArticleStatsProvider` **인터페이스만** 정의해 주입받고(테스트는 fake), 실제 조회는 TASK 08이 채운다. **신규 이벤트는 이번 배치가 곧 전체 집합이라 provider 없이도 정확**하고, **편입 이벤트는 provider가 준 기존 통계와 이번 배치 기사를 합산**해 전체를 재계산한다. provider 미주입 시 기본은 배치 기사만으로 계산(오프라인에서도 파이프라인이 죽지 않음, 편입 이벤트는 근사). — TASK 05의 `RecentEventProvider`/centroid가 "집계·상태 유지는 backend 소유"였던 것과 같은 정신이다.
- **왜 언론사 가중치를 config 테이블로 두나(하드코딩 금지)**: 매체별 가중은 정책값이고 튜닝 대상이며 **아직 미확정(CLAUDE.md §8)**이다. 코드에 흩지 말고 `config.py` 한 곳(`IMPORTANCE_PUBLISHER_WEIGHTS`)에 모아 임시값으로 두고 실데이터로 확정한다. 미등록 언론사는 기본값으로 처리한다(누락돼도 계산이 죽지 않게).
- **DB 접근 금지**: importance는 순수 계산만. 기존 통계 조회·저장은 backend HTTP(TASK 08) (CLAUDE.md §2-1).

## 3. 요구사항

### 3.1 `config.py` — importance 설정 (하드코딩 금지)
1. **세 신호 가중치**: `IMPORTANCE_W_VOLUME`, `IMPORTANCE_W_PUBLISHER`, `IMPORTANCE_W_SENTIMENT`. 계수는 임시값(실데이터 튜닝, pipeline_spec §9). 세 신호의 하위 점수는 서로 크기 스케일이 다를 수 있으므로, 각 하위 점수를 비슷한 범위로 정규화하거나(권장) 가중치로 스케일을 흡수한다(주석으로 튜닝 대상 표기).
2. **언론사 가중치 테이블**: `IMPORTANCE_PUBLISHER_WEIGHTS: dict[str, float]` — 언론사명 → 가중치. **⚠️ 미확정(CLAUDE.md §8) → 임시값**임을 주석으로 명시. 키는 `RSS_CANDIDATES`(CLAUDE.md §5)의 언론사명과 정합을 맞춘다(표기 흔들림 주의).
   - **확정 전 운용 정책(default-only)**: 표가 확정되기 전에는 `IMPORTANCE_PUBLISHER_WEIGHTS`를 **비우고 전 매체를 `IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT`로** 운용해도 된다(언론사 항이 상수화 → 랭킹은 volume·감성이 결정). **임의값을 "확정값"처럼 굳히지 않는다** — 실데이터로 확정될 때 표를 채운다.
3. **미등록 언론사 기본값**: `IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT` — 테이블에 없는 언론사(또는 `publisher=None`)의 기본 가중치. 누락돼도 계산이 죽지 않게(방어값).
4. **기사 수 변환 방식**: `IMPORTANCE_VOLUME_MODE: str`(예: `"log1p"` | `"sqrt"` | `"linear"`). bool 토글이 아니라 **문자열 모드**로 둔다 — 나중에 `log1p`·`sqrt`·`linear` 등을 실험할 여지가 크므로 값 하나로 감쇠 함수를 갈아끼울 수 있게 한다. 기본은 `"log1p"`(근접 중복 홍수가 순위를 독점하지 못하게, §2). 변환은 `services/importance.py`가 이 모드에 따라 선택하고, 미지원 값이면 로깅 후 기본 모드로 폴백한다. 튜닝/실험 대상.

### 3.2 `services/importance.py` — 중요도 계산 서비스 (순수·결정적)
> **⚠️ 계산 경계 규칙**: importance는 **관측 신호의 결정적 함수**다. LLM(`services/llm.py`)·감성 모델(`services/finbert.py`)을 호출하지 않고, DB/backend도 직접 부르지 않는다. 기존 이벤트 통계가 필요하면 **주입된 `EventArticleStatsProvider`로만** 얻는다(절대규칙 1, 실제 구현은 TASK 08).

1. **`publisher_weight(publisher: str | None) -> float`**: `IMPORTANCE_PUBLISHER_WEIGHTS`에서 조회, 없거나 `None`이면 `IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT`. 표기 정규화(공백 등)는 최소한으로 하고 규칙을 주석에 남긴다. **⚠️ 테이블 값은 미확정(임시)**.
2. **`sentiment_magnitude(article: Article) -> float | None`**: 기사 1건의 **감성 절대값(사건 강도)**.
   - **⚠️ `sentiment_score`의 의미**: 이는 KR-FinBert의 **분류 confidence**(예측 라벨의 softmax 최댓값, TASK 04)다. importance는 감성의 **방향(긍/부)이 아니라 모델이 판단한 감성 강도**를 쓰므로, 이 confidence를 그대로 강도로 삼는다. 따라서 **긍정 0.99와 부정 0.99는 importance 기여가 같다**(방향은 버리고 세기만 본다 — 의도된 동작).
   - `sentiment`가 **긍정/부정**이면 세기 = `sentiment_score`(0~1 confidence, TASK 04). 방향(부호)은 쓰지 않는다.
   - `sentiment`가 **중립**이면 강도 `0.0`(중립은 강도 없음, 단 집계에는 포함).
   - `sentiment`가 **`None`(감성 없음)**이면 `None`을 반환해 **집계에서 제외**하도록 신호(강제 중립 금지, TASK 04 §4.1).
3. **`compute_importance(articles, existing=None) -> float`**: 한 이벤트의 importance.
   - **총 기사 수(volume)** = `len(articles) + (existing.article_count if existing else 0)`. `IMPORTANCE_VOLUME_MODE`(`"log1p"`/`"sqrt"`/`"linear"`)에 따라 변환한다(기본 log1p, 미지원 값은 로깅 후 기본 폴백).
   - **언론사(publisher)** = 이번 배치 기사들의 언론사 ∪ `existing.publishers`(있으면)의 **distinct 집합**에 대해 `publisher_weight`의 **합(sum)으로 확정**한다(평균 아님). **distinct로 묶는 이유**: 같은 매체가 같은 사건을 여러 번 써도 언론사 신호가 부풀지 않게 한다(그 중복은 volume이 이미 반영). **합(sum)으로 정하는 이유**: 더 많은·더 권위 있는 매체가 함께 다룰수록 사건의 도달·신뢰가 커지므로, 매체가 늘수록 언론사 항이 단조 증가해야 한다(평균은 매체가 늘어도 커지지 않아 "여러 매체가 다뤘다"는 신호를 못 살린다). 가중치 테이블은 **오직 여기(config)**에서만 적용한다(backend에 중복 두지 않도록 provider는 원자료 `publishers`를 반환).
   - **감성 강도(sentiment)** = 감성 있는 기사들의 `sentiment_magnitude` **평균**. 배치 기사에서 `None`이 아닌 값들의 합·개수에 `existing`의 `sentiment_magnitude_sum`·`sentiment_count`를 합산해 (합/개수)로 계산. 감성 있는 기사가 **0건이면 감성 항 0**(환각 금지).
   - `importance = IMPORTANCE_W_VOLUME·f(volume) + IMPORTANCE_W_PUBLISHER·g(publisher) + IMPORTANCE_W_SENTIMENT·h(sentiment)`. 세 하위 점수를 각각 산출해 결합한다. (디버깅·evals용 하위 점수 분해가 필요하면 선택적으로 노출하되, `Event`에는 최종 스칼라만 저장한다 — 감성 분포·하위점수를 Event에 저장하지 않는다.)
   - **결정성**: 같은 입력이면 항상 같은 출력. 난수·시간·LLM 없음. 값·가중치·테이블은 전부 `config`에서 읽는다(하드코딩 금지).
4. **후보 통계 조회 인터페이스 `EventArticleStatsProvider`(Protocol)**: `get_event_article_stats(event_id: str) -> EventArticleStats | None`. **이미 저장된** 그 이벤트의 누적 기사 통계를 반환한다(이번 배치 기사는 아직 미저장이므로 **중복 없음**). TASK 06은 이 시그니처만 정의하고, TASK 08이 Neo4j/PostgreSQL 조회로 구현한다. **미주입 시 기본 provider는 `None`을 반환**(backend 미연결에서도 파이프라인이 죽지 않고, 배치 기사만으로 계산 — 신규 이벤트는 정확, 편입 이벤트는 근사).
5. **부수효과 최소화**: 입력(기사들 + 기존 통계) → 출력(점수). 저장·DB 접근 없음 (CLAUDE.md §2-1). `Event`/state 갱신은 노드가 한다.
6. **importance 외 판단을 하지 않는다**: 이 서비스는 중요도 스칼라만 낸다. 감성 판정·병합·분포 집계를 여기 섞지 않는다(단일 책임, CLAUDE.md §7).

### 3.3 `schemas/event.py` — `EventArticleStats` (⚠️ TASK 01)
기존(저장된) 이벤트의 **전체 재계산에 필요한 누적 원자료만** 담는다. backend(TASK 08)가 채워 반환하고, TASK 06은 읽어서 이번 배치와 합산만 한다.
- `article_count: int` — 저장된 관련 기사 총 건수(volume 합산용).
- `publishers: list[str]` — 저장된 관련 기사의 언론사. 가중치 테이블은 agent가 적용하므로 **원자료 문자열**로 반환한다. **의미상 distinct 집합**(언론사 신호가 distinct 합이므로 backend는 중복 없이 채운다). 타입은 `set[str]`이 의미에 더 맞지만, 이 모델은 **backend HTTP(JSON) 계약**을 건너므로 직렬화 호환을 위해 **`list[str]`으로 두고 "중복 없이 채운다"를 계약으로** 명시한다(agent는 방어적으로 다시 distinct 처리).
- `sentiment_magnitude_sum: float` / `sentiment_count: int` — 감성 있는(=`None` 아님) 저장 기사들의 강도 합과 개수(평균 재결합용). 평균을 미리 계산해 넘기지 않는 이유는 배치와 **합산**해야 하기 때문(합·개수 단위로 넘겨야 정확히 결합).
- `updated_at: datetime | None`(선택) — 이 통계가 backend에서 산출된 시각. **필수는 아니나 디버깅용 권장**("importance가 왜 이 값이지?"를 추적할 때 통계 신선도를 알 수 있음). 계산에는 쓰지 않는다.

### 3.4 `nodes/importance.py` — 중요도 노드 (얇게)
1. `state["articles"]` 중 **`event_id`가 배정된 기사**(= 병합까지 통과, TASK 05)를 이벤트별로 묶는다. 노드는 순서만 담당하는 얇은 껍데기 (CLAUDE.md §2-2).
2. **영향 이벤트 집합**: 이번 배치 기사들의 `event_id` **집합**을 만든다(신규 이벤트 + 편입된 기존 이벤트 모두 포함 — 편입 기사도 `event_id`를 가지므로 자연히 포함된다).
3. **provider 주입**: backend 조회 provider를 주입받아 각 `event_id`에 대해 `provider.get_event_article_stats(event_id)`로 기존 통계를 얻고(미주입 시 `None`) `importance.compute_importance(그 이벤트의 배치 기사, existing)`을 호출한다. 노드는 backend를 직접 호출하지 않는다(절대규칙 1).
4. **결과 반영**:
   - **모든 영향 이벤트**: `state["importance_by_event_id"][event_id] = score`로 실어, TASK 08(저장)이 **신규뿐 아니라 편입(기존) 이벤트에도** importance를 반영하게 한다. **타입은 `dict[str, float]`이며 키는 이벤트의 `canonical_id`(= `Article.event_id`), 값은 importance 점수**다(키가 DB id가 아니라 canonical_id임을 명확히).
   - **신규 이벤트**(`state["events_by_id"]`에 있는 것): 그 `Event.importance = score`로 직접 채운다.
5. **실패 격리**: 한 이벤트의 계산이 실패해도 예외로 파이프라인을 죽이지 않는다. 로깅 후 그 이벤트만 skip(importance 미설정), 나머지 계속 (CLAUDE.md §7).
6. **모델·집계 로직을 노드에 두지 않는다**: 노드는 `services/importance.py`만 호출한다. 가중치·감쇠·합산 로직은 서비스에 둔다 (CLAUDE.md §2-2).
7. 대상(`event_id` 배정된 기사) 0건이면 예외 없이 그대로 통과(환각 금지: 없으면 없는 대로 — CLAUDE.md §2-5). 후속·리포트가 "데이터 제한"으로 처리한다.

## 4. 인터페이스 / 구현 규칙

> 아래는 확정 시그니처(초안). 함수명·반환 타입은 이대로 구현하되, 설정값은 `config.py`에서 읽는다. 함수 본문(로직)은 비워 둔다.

```python
# config.py (발췌) — importance 설정. 값·테이블은 실데이터 튜닝 대상(주석 표기).
IMPORTANCE_W_VOLUME: float = 0.5      # 기사 개수(노출량) 가중 — 튜닝 대상
IMPORTANCE_W_PUBLISHER: float = 0.3   # 언론사 가중 — 튜닝 대상
IMPORTANCE_W_SENTIMENT: float = 0.2   # 감성 절대값(사건 강도) 가중 — 튜닝 대상
IMPORTANCE_VOLUME_MODE: str = "log1p"  # 기사 수 변환: "log1p" | "sqrt" | "linear". 함수 교체 여지 위해 bool 아닌 모드. 미지원 값→log1p 폴백 — 튜닝/실험 대상

# ⚠️ 언론사 가중치 테이블: 미확정(CLAUDE.md §8) — 임시값. 실데이터로 확정.
#    키는 RSS_CANDIDATES(CLAUDE.md §5)의 언론사명과 정합.
IMPORTANCE_PUBLISHER_WEIGHTS: dict[str, float] = {
    "매일경제": 1.0, "한국경제": 1.0,          # 주요 경제지
    "조선일보": 0.9, "동아일보": 0.9, "경향신문": 0.9, "한겨레": 0.9,  # 종합지
    # ... 나머지 후보 매체 임시값
}
IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT: float = 0.5   # 테이블에 없는 언론사/None 기본값(방어)
```

```python
# schemas/event.py (발췌 — TASK 01에 정의됨. 여기서는 계약 재확인)
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field

class EventArticleStats(BaseModel):
    """기존(저장된) 이벤트의 누적 기사 통계. EventArticleStatsProvider가 반환,
    전체 재계산 시 이번 배치와 '합산'하는 입력. 이번 배치 기사는 아직 미저장이라 중복 없음."""
    article_count: int = 0                    # 저장된 관련 기사 총 건수(volume)
    # 저장 기사 언론사(가중치는 agent가 적용 → 원자료). 의미상 distinct 집합이나
    # backend HTTP(JSON) 계약이라 list로 두고 "중복 없이 채운다"를 계약으로. agent도 방어적 distinct.
    publishers: list[str] = Field(default_factory=list)
    sentiment_magnitude_sum: float = 0.0      # 감성 있는(None 아님) 저장 기사 강도 합
    sentiment_count: int = 0                  # 감성 있는 저장 기사 개수(평균 재결합용)
    updated_at: datetime | None = None        # (선택) 통계 산출 시각. 디버깅용, 계산엔 미사용
```

```python
# services/importance.py — 중요도 계산(객관 신호, 결정적). LLM·DB 없음.
# ⚠️ 기존 이벤트 통계는 주입된 EventArticleStatsProvider로만. DB/backend 직접 호출 금지(절대규칙 1).
from __future__ import annotations
from typing import Protocol
from schemas.article import Article
from schemas.event import EventArticleStats   # ⚠️ TASK 01 추가

class EventArticleStatsProvider(Protocol):
    def get_event_article_stats(self, event_id: str) -> EventArticleStats | None:
        """이미 저장된 그 이벤트의 누적 기사 통계 반환(이번 배치 기사는 미포함 → 중복 없음).
        실제 구현은 TASK 08. 미주입 기본은 None(배치 기사만으로 계산)."""
        ...

def publisher_weight(publisher: str | None) -> float:
    """IMPORTANCE_PUBLISHER_WEIGHTS 조회. 없으면/None이면 IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT.
    ⚠️ 테이블 값은 미확정(임시). 가중치 적용은 오직 여기서만."""
    ...

def sentiment_magnitude(article: Article) -> float | None:
    """감성 절대값(사건 강도). 긍정/부정 → sentiment_score, 중립 → 0.0, None → None(집계 제외).
    방향(부호)은 쓰지 않고 세기만 쓴다(importance는 좋다/나쁘다가 아니라 중요하다/아니다)."""
    ...

def compute_importance(
    articles: list[Article], existing: EventArticleStats | None = None,
) -> float:
    """한 이벤트 importance = W_VOLUME·f(총 기사수) + W_PUBLISHER·g(언론사) + W_SENTIMENT·h(감성 강도).
    - 총 기사수/언론사/감성은 (existing + 이번 배치 기사)를 합산해 산출(배치 기사=미저장 신규라 중복 없음).
    - 언론사: 배치 ∪ existing.publishers의 distinct에 publisher_weight '합(sum)'(평균 아님, 테이블은 여기서만).
    - 감성: None 아닌 강도의 평균((배치 합 + existing.sum)/(배치 수 + existing.count)). 감성 0건이면 감성 항 0.
    - LLM·DB 호출 없음(결정적). 값·가중치·테이블은 config에서 읽는다.
    """
    ...
```

```python
# nodes/importance.py — 얇은 중요도 노드
# ⚠️ backend를 직접 호출하지 않는다(주입된 EventArticleStatsProvider 사용). 집계 로직은 services에.
from __future__ import annotations
import services.importance as importance

def importance_node(state: dict, provider=None) -> dict:
    """event_id가 배정된 기사를 이벤트별로 묶어 importance 계산.
    - 영향 이벤트 = 이번 배치 기사들의 event_id 집합(신규 + 편입 모두 포함).
    - 각 이벤트: provider.get_event_article_stats(event_id)(미주입 시 None) → compute_importance.
    - 모든 영향 이벤트를 state["importance_by_event_id"][event_id]=score 로 실어 TASK 08이 편입 이벤트에도 반영.
    - 신규 이벤트(state["events_by_id"])는 Event.importance에 직접 반영.
    - 한 이벤트 실패해도 로깅 후 skip, 파이프라인 계속. 대상 0건이면 예외 없이 통과.
    """
    ...
```

### 4.1 importance 계산 규칙 요약 (객관 계산·환각 금지)
| 신호 | 입력 | 규칙 |
|---|---|---|
| 기사 개수(volume) | 배치 기사 수 + `existing.article_count` | `IMPORTANCE_VOLUME_MODE`(`log1p`/`sqrt`/`linear`, 기본 log1p)로 변환 — 근접중복 독점 방지 |
| 언론사 가중치(publisher) | 배치 ∪ `existing.publishers` **distinct**의 가중치 **합(sum)** | `IMPORTANCE_PUBLISHER_WEIGHTS`(⚠️ 미확정) 적용, 미등록/None → 기본값. 평균 아님(매체 수↑ → 항↑) |
| 감성 절대값(sentiment) | `None` 아닌 기사들의 `sentiment_magnitude` 평균 | 긍/부 → `sentiment_score`, 중립 → 0, **None → 제외**. 감성 0건이면 항 0 |

- **importance는 LLM이 생성하지 않는다**: 세 신호의 결정적 함수. `services/llm.py` 미호출.
- **감성은 세기만, 방향은 버린다**: 강한 긍정·강한 부정 모두 중요도↑, 중립↓. (병합이 감성을 아예 안 쓰는 것과 구분.)
- **`sentiment=None`은 강제 중립으로 세지 않는다**: 감성 항 분모에서 제외(TASK 04 §4.1과 정합).
- **분포는 저장하지 않는다**: 이 단계는 스칼라 하나만. 긍/중/부 건수는 조회 시 실시간 집계(TASK 09).

### 4.2 cleanup(7일 롤링) 이후 importance 갱신 정책 (stale 방지)
> **문제**: importance는 **이번 배치에 새 기사가 편입된 이벤트만** 재계산된다(§3.4-2). 그런데 7일 롤링 삭제(pipeline_spec §10·SCHEMA_SPEC §5)는 배치와 무관하게 이벤트의 기사 집합을 줄인다. **새 기사가 더는 안 붙는 이벤트**는 기사가 삭제돼도 옛 importance를 그대로 유지해, 실제보다 부풀려진 점수로 TOP 정렬을 계속 차지한다(예: 기사 100건·importance 10 → 7일 경과로 5건만 남아도 importance는 여전히 10).

- **소유·해결(backend)**: cleanup은 backend가 수행하며(절대규칙 1), **삭제로 기사 집합이 바뀐 이벤트의 `Event.importance`를 cleanup 트랜잭션 안에서 재계산**하는 것을 backend 계약으로 둔다(SCHEMA_SPEC §5). 재계산 공식·가중치는 이 문서(§3.2)의 것과 동일해야 하므로, **importance 계산 규칙은 ai(agent)와 backend가 공유하는 단일 정의**임을 명시한다(공식이 두 곳에서 갈라지지 않도록 api_contract 승격 시 "importance 공식 소유·공유" 항목으로 고정).
  - 대안(차선): backend가 조회(질의 흐름) 시점에 현재 기사 집합으로 importance를 재계산해 정렬에 쓴다. 저장 스냅샷을 신뢰하지 않는 방식이라 stale이 없지만 조회 비용이 오른다. **기본은 cleanup 시 재계산**으로 두고, 조회 시 재계산은 backend 판단에 맡긴다.
- **agent(TASK 06) 경계**: 이 단계는 **배치에서 새 기사가 편입된 이벤트의 importance만** 계산한다(기존과 동일). cleanup으로만 기사가 준 이벤트의 재계산은 **backend 소유**이고 여기 범위 밖이다. 다만 이 간극을 문서가 명시적으로 **소유**하게 하여(이전엔 어느 문서도 침묵) "알려진 근사"로 방치되지 않게 한다.

## 5. 규칙·제약 (CLAUDE.md)
- **§2-4 감성·점수는 전용 모델·계산, LLM 아님.** importance는 객관 신호의 결정적 계산이다. 이 단계 어디에도 LLM 호출이 없다(감성도 다시 판정하지 않고 TASK 04 결과를 소비만).
- **§2-5 환각 금지.** 없는 감성(`None`)을 지어내지 않고 제외. 감성 있는 기사 0건이면 감성 항 0. 근거 없는 수치를 만들지 않는다.
- **§5 감성 count 미저장·조회 시 집계.** importance는 정렬용 스칼라 하나만 Event에 둔다. 긍/중/부 분포를 Event에 저장하지 않는다.
- **§2-1 DB 직접 접근 금지.** 기존 이벤트 통계 조회는 주입된 `EventArticleStatsProvider`로만(실제 구현 TASK 08 backend HTTP). 저장도 TASK 08.
- **§2-2 nodes는 얇게, 로직은 services.** 가중치·감쇠·합산 계산은 `services/importance.py`. 노드는 묶기·반영만.
- **§7 예외는 로깅·skip, 파이프라인 계속. 설정값 하드코딩 금지**(가중치·언론사 테이블·기본값·감쇠 옵션은 config).
- **§8 미확정 존중.** 언론사 가중치 테이블은 임시값 + 주석으로 미확정 표기(실데이터 튜닝).

## 6. 완료 조건 (DoD)
- [ ] `config.py`에 `IMPORTANCE_W_VOLUME`/`IMPORTANCE_W_PUBLISHER`/`IMPORTANCE_W_SENTIMENT` + `IMPORTANCE_PUBLISHER_WEIGHTS`(⚠️ 미확정 주석) + `IMPORTANCE_DEFAULT_PUBLISHER_WEIGHT` + `IMPORTANCE_VOLUME_MODE`(문자열 모드, 기본 `"log1p"`)가 정의됨. 가중치·테이블 하드코딩 없음.
- [ ] `EventArticleStats`가 `schemas/event.py`에 Pydantic 모델로 추가됨(article_count·publishers(distinct 계약, list[str])·sentiment_magnitude_sum·sentiment_count·`updated_at`(선택)). ⚠️ TASK 01에 반영. (`Event.importance` 필드는 이미 존재 — 새로 만들지 않음.)
- [ ] `services/importance.py`가 `importance = 기사 개수 + 언론사 가중치 + 감성 절대값`(config 가중치 결합)으로 **결정적** 계산함. 같은 입력→같은 출력, 난수·시간·LLM 없음.
- [ ] `publisher_weight`가 `IMPORTANCE_PUBLISHER_WEIGHTS` 조회 + 미등록/None → 기본값. 가중치 테이블 적용은 이 함수에만 있음.
- [ ] `sentiment_magnitude`가 긍/부 → `sentiment_score`, 중립 → 0, **`None` → 집계 제외**로 동작. 방향(부호) 미사용.
- [ ] `compute_importance`가 `existing`(기존 통계)과 이번 배치 기사를 **합산**해 전체 재계산함(신규 이벤트는 provider 없이도 정확, 편입은 provider로 정확·미주입 시 근사). 감성 있는 기사 0건이면 감성 항 0.
- [ ] `EventArticleStatsProvider` **인터페이스만** 정의하고 backend/DB를 직접 호출하지 않음. 미주입 기본 provider는 `None` 반환.
- [ ] **importance 계산에 LLM을 사용하지 않음**(services/llm.py 미호출). 감성을 다시 판정하지 않음(TASK 04 결과 소비).
- [ ] **감성 분포(긍/중/부 건수)를 이 단계에서 집계·저장하지 않음**(정렬용 스칼라 하나만).
- [ ] `nodes/importance.py`가 `event_id` 배정 기사를 이벤트별로 묶어 계산하고, **모든 영향 이벤트**를 `state["importance_by_event_id"]`에, **신규 이벤트**의 `Event.importance`를 채움. services만 호출.
- [ ] 한 이벤트 실패 시 로깅 후 skip, 나머지 계속. 대상 0건일 때 예외 없이 통과.

## 7. 테스트
- **대상 파일**: `tests/test_importance.py`(**신규** — 존재하지 않으므로 생성).
- **mock 전략**: 실제 backend·모델을 호출하지 않는다 (CLAUDE.md: tests는 mock 기반). importance는 순수 계산이라 대부분 mock 없이 검증 가능하고, 기존 통계는 **fake `EventArticleStatsProvider`**로 주입한다.
  - **`publisher_weight`**: 테이블 등록 매체 → 해당 값, 미등록 매체/`None` → 기본값.
  - **`sentiment_magnitude`**: 긍정/부정 → `sentiment_score` 그대로, 중립 → 0.0, `None` → `None`(집계 제외 신호).
  - **`compute_importance`(핵심)**:
    - 기사 수↑ → importance↑(단, `IMPORTANCE_VOLUME_MODE`가 `log1p`/`sqrt`면 체감), 언론사 가중치↑ → ↑, 감성 강도↑ → ↑ (각 신호 단조성). 모드별(`log1p`/`sqrt`/`linear`) 변환이 적용되는지, 미지원 모드는 기본으로 폴백하는지.
    - **언론사 = distinct 합(sum)**: 같은 매체가 여러 기사를 써도 언론사 항이 안 오르고(distinct), 서로 다른 매체가 늘면 항이 오른다(sum → 단조 증가). 평균이 아님을 검증.
    - **감성 방향 무관·세기만**: 강한 긍정과 강한 부정이 (다른 조건 동일 시) 같은 감성 기여를 냄.
    - **`sentiment=None` 제외**: 감성 None 기사가 섞여도 감성 항이 그 기사를 분모에서 제외. 전 기사 `None` → 감성 항 0(예외 없음).
    - **중립 포함**: 중립 기사는 강도 0으로 분모에 포함(감성 항을 희석).
    - **결정성**: 같은 입력 두 번 호출 → 동일 값.
    - **existing 합산**: fake `EventArticleStats`(count·publishers·감성 합/개수)를 주면 배치와 합산해 전체가 재계산되는지(편입 시나리오). `existing=None`이면 배치만으로 계산(신규 시나리오).
  - **`importance_node`**: (1) `event_id`별로 묶여 이벤트마다 점수가 나오는지, (2) `state["importance_by_event_id"]`에 **신규+편입 모두** 실리는지, (3) `state["events_by_id"]`의 신규 `Event.importance`가 채워지는지, (4) provider 주입 시 편입 이벤트가 기존 통계와 합산되는지·미주입 시 배치만으로 계산되는지, (5) 한 이벤트 실패 시 나머지 계속, (6) 대상 0건일 때 예외 없이 통과.
  - **LLM 미사용**: importance 경로가 `services/llm.py`를 호출하지 않음을 확인(객관 계산).
- **경계 케이스**: 이벤트 기사 1건, 전 기사 `sentiment=None`, `publisher=None`, 미등록 언론사, `existing` 있음/없음, 배치 내 여러 이벤트.
- **evals 연계**: 중요도 품질(랭킹 상관 등)은 이후 `evals/` 축에서 정답셋 대조로 다룬다(모델 없이 결정적 채점). 여기 tests는 공식·신호·분기·합산 검증.
- 후속 TASK(07 그래프·08 저장·09 리포트 정렬)가 `Event.importance`·`state["importance_by_event_id"]`·`EventArticleStatsProvider`를 재사용하므로, 필드·인터페이스를 바꾸면 TASK 01부터 함께 수정한다.

## 8. 구현 계약 요약 (I/O)
| 입력 | 출력 | 호출 가능 | 호출 금지 | 실패 시 |
|---|---|---|---|---|
| `event_id` 배정 기사 (+ 주입 `EventArticleStatsProvider`) | `state["importance_by_event_id"]`, 신규 Event.`importance` | `services/importance`(순수 계산) | LLM, 감성 재판정, DB/backend 직접 | 이벤트별 실패 skip, provider 미주입=배치만 근사 |
