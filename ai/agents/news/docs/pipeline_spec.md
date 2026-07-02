# 파이프라인 기획서 (news 에이전트)

> 뉴스 수집 → 분석 → 지식 그래프 구성 → HTML 리포트까지 전체 설계.
> 상세 근거는 event_merge.md, model_choice.md 참조.

## 1. 개요

국내 언론사 뉴스를 수집·분석해 종목별 여론(감성)과 핵심 이벤트를
지식 그래프로 구성하고, 중요도·출처와 함께 HTML 리포트로 제시하는 자기완결 에이전트.

- 입력: 종목(또는 섹터)
- 출력: HTML 리포트 (감성 게이지 + TOP 이벤트)

## 2. 두 흐름

### 배치 흐름 (매시간, 백그라운드)
```
RSS 수집 → URL 중복 체크 → 본문 크롤링
  → LLM 추출(요약·개체·이벤트) + KR-FinBert 감성 + arctic-embed 임베딩
  → 이벤트 병합 → importance 계산
  → backend 경유 저장 (PostgreSQL + Neo4j)
```
데이터만 쌓는다. HTML은 만들지 않는다.

### 리포트 흐름 (사용자 요청 시)
```
종목 선택 → backend 조회(이벤트·감성·importance)
  → HTML 리포트 생성
```
저장된 데이터를 읽어 그리기만. 수집·분석하지 않는다.

## 3. 모델 스택

| 역할 | 모델 |
|---|---|
| 추출(요약·개체·이벤트) | Qwen3 30B-A3B (로컬, MoE) |
| 감성분석 | KR-FinBert-SC |
| 임베딩(summary) | arctic-embed-l-v2.0-ko |

LLM은 추출만. 감성 판정·점수는 전용 모델이 담당(환각 방지).

## 4. 데이터 수집

- 국내 언론사 전체기사/경제 RSS를 매시간 수집. 원문 직링크 확보, 인증 불필요.
- **RSS 요약을 안 쓰는 이유**: 언론사마다 요약 성격이 다름(진짜 요약 vs 앞 100자 자르기 vs 없음).
  그대로 임베딩하면 같은 내용도 다른 벡터가 나와 병합이 어긋남.
  → 본문을 크롤링하고 LLM이 통일된 요약 생성.
- 중립 제목("실적 발표")은 본문이 있어야 감성 방향이 잡힘.

## 5. AI 분석

### LLM 추출 (Pydantic 강제)
기사당 1회 호출로 JSON 반환. 항목별 호출 안 함(9배 절감).
```
{ summary, companies, people, industries, events, countries, keywords }
```
감성·영향도 없음(감성은 KR-FinBert, 영향도는 importance로 대체).

### 감성분석
KR-FinBert-SC로 기사별 긍/중/부.

## 6. 이벤트 병합
summary 임베딩 + company + time 가중 점수로 여러 기사를 한 이벤트로 묶음.
상세는 event_merge.md 참조.

## 7. 저장 (backend 경유)
- PostgreSQL: 기사 원본·요약·임베딩·감성 (News 원본)
- Neo4j: Event 중심 그래프 (Company·Event·Keyword·Person + 관계, News는 참조만)
- DB 직접 접근 금지. backend HTTP로만.

## 8. 지식 그래프 (Neo4j)
- Event가 중심. `Company -PARTICIPATES_IN-> Event` (여러 회사가 한 이벤트 공유 가능).
- News 원본은 PostgreSQL, Neo4j엔 news_id 참조만.
- Event에 importance(중요도) 보관 → 최신순 아닌 중요도순 정렬.

## 9. importance (중요도)
```
importance = 기사 개수 + 언론사 가중치 + 감성 절대값
```
LLM이 지어내는 값이 아니라 객관 신호로 계산(근거 있음).

## 10. 7일 롤링 삭제
7일 경과분 삭제 → Event 기사수 0이면 삭제 → 고아 Keyword·Person 삭제.
Company는 유지.

## 11. 질의 (Graph → PostgreSQL → LLM)
Neo4j로 이벤트·관계 뼈대 조회 → PostgreSQL에서 기사 요약 → LLM이 답변.
그래프만 보면 "왜"를 설명 못 하므로 본문 요약까지 봄.

## 12. 단계적 구현
- MVP: 수집→크롤링→감성→이슈·게이지 (그래프 없이 완결)
- 2차: LLM 추출→병합→Neo4j + importance
- 3차: RELATED_TO, 2단계 질의, pgvector 유사 검색
