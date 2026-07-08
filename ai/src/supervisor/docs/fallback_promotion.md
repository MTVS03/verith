# Fallback → canonical 승격 플로우 (승인형)

`ai/src/supervisor/docs/fallback_promotion.md`

질문 중 fallback 으로 반복 resolve 되는 표현을 **사람 승인 후에만** canonical(stocks/stock_aliases)로 올리기
위한 운영 경계. **핵심 원칙: 질문 처리 경로는 canonical read-only. 실시간 자동 승격 없음. collect → review →
approve → apply 를 강제 분리한다.**

## 위상 정리
- **ephemeral(persisted=false)**: 질문 중 fallback resolve 결과. 이번 요청에만 쓰이는 임시 context. 정본 아님.
- **candidate**: ephemeral success 를 오프라인 집계한 승격 **후보**. 여전히 정본 아님(검토 대상).
- **canonical**: `stocks`(종목 universe 정본) · `stock_aliases`(수동/운영 큐레이션) · `stock_corp_codes`(DART 매핑).
  supervisor 는 여기에 **쓰지 않는다** — 후보 관측·제안까지만.

## 파이프라인 (4단계, 분리 강제)
1. **collect** — 질문 경로는 관측 event 만 emit. `JsonlPromotionCaptureSink`(**opt-in**, 기본 미배선)를 켜면
   resolved fallback 이 capture JSONL 로 append 된다(raw query 아님 — normalized_query 만). 집계는
   `scripts/collect_fallback_candidates.py`(오프라인, canonical 미접근)가 candidate JSONL 로 만든다.
2. **review** — 사람이 candidate JSONL 을 검토. 후보 기준(아래)으로 승격/기각 판단.
3. **approve** — canonical 소유자가 승인. candidate 의 `promotion_status` 를 approved/rejected 로 편집.
4. **apply** — backend 소유자가 승인분만 seed/sync 로 반영(질문 경로와 완전 분리).

## 승격 후보 기준
- **A. stock_addition** — canonical `stocks` 에 종목 자체가 없음(신규 상장 등). 희소(universe=2,607 전체 주권).
- **B. alias_addition** — 종목은 canonical 에 있고 **표현**(영문/공시명/로마자/구명)만 없어 fallback 으로만 풀림.
  대다수가 여기.
- **C. 승격 금지** — ambiguous 였던 표현 / 일회성·노이즈(observed_count 낮음) / source 충돌 / 짧은 이름(오탐
  위험, 정규화 len<3 은 애초 후보화 안 함) / 범용성 낮음.

판단 신호(집계에 기록): `observed_count`(반복성) · `final_source`(curated/dart) · `match_types`
(code/name/alias exact) · `stock_code` 단일 안정성 · canonical 이 계속 not_found 인지 · `needs_canonical_check`.

분류 규칙(집계 hint, 최종은 사람):
- `final_source="dart"` → **alias_addition**, canonical 재확인 불필요(스냅샷이 stocks JOIN 산물 → 종목 존재 확정).
- 그 외(curated 등) → alias_addition 이되 **needs_canonical_check=true**(canonical 미존재면 stock_addition).

## 후보 아티팩트 (저장 매체 = JSONL)
- 선택 이유: repo 선례(`agents/fundamental/data/.runs/history.jsonl`)와 일관, append·사람편집 용이, DB schema
  확장 불필요(이 브랜치는 운영 경계 설계지 canonical schema 변경 아님).
- capture: `planning/data/fallback_capture.jsonl`(opt-in sink 산출, **gitignore 권장** — 관측 데이터).
- candidate: `planning/data/fallback_promotion_candidates.jsonl`(집계 산출, 리뷰 대상). 포맷 예시는
  `*.sample.jsonl` 참고.
- **저장 정책**: raw query 원문 미저장. `normalized_query` 만(정책 허용). 예시도 normalized 기준.

## 승인 주체 / 반영 주체 (기존 소유권 존중)
| 역할 | 담당 | 하는 일 |
|---|---|---|
| collect + propose | **supervisor 소유자** | 관측 emit, capture/collect 실행, 후보 목록 제출. canonical write 안 함 |
| approve (`stocks`) | **backend 소유자** | 종목 universe·migration 정본. stock_addition 승인 |
| approve (`stock_aliases`) | **domain/ops 큐레이터** | alias 는 수동/운영 큐레이션(db_boundaries.md) — alias_addition 승인 |
| apply | **backend 소유자** | `sync_stocks`/`seed_*`/`sync_corp_codes` 실행(질문 경로와 분리) |

## seed/sync 반영 경로 기준
- **stock_addition** → `stocks`: 신규 상장은 대개 다음 `sync_stocks --apply`(KIS master)에서 자연 편입. 특수분은 운영 seed.
- **alias_addition** → `stock_aliases`: `constants/stock_aliases.py` + `seed_stock_aliases`(수동 큐레이션 소유권 존중).
- **corp_name/공시명 계열** → DART 스냅샷 갱신(fallback 보조) 또는 alias 승격(canonical resolver 가 직접 풀게).
- **승격 완료 후**: canonical resolver 가 직접 푸는 표현은 fallback **curated source 에서 축소/삭제** 가능(중복 제거).
  즉 "fallback 을 계속 부를지 vs 정본 승격 후 resolver 가 직접 풀지"의 기준 = canonical 이 그 표현을 직접
  resolve 하게 되면 fallback 의무 종료.

## DART 스냅샷 갱신 규칙
- **위상**: canonical truth 아님, **fallback 보조 artifact**(read-only).
- **누가**: canonical 소유자(backend/ops), supervisor 소유자 제안. **언제**: stocks/corp_codes sync 후 정기, 또는 승격 반영 후.
- **source**: `stock_corp_codes JOIN stocks`(SQL 은 스냅샷 json `_provenance`/`_generated_query`).
- **유지 정책**: **additive 만**(정규화 후 stock_name 과 다르고 len≥3). **canonical resolver 가 직접 푸는 표현은
  스냅샷에서 제거**(중복 제거 → fallback 축소).

## 하지 않는 것 (이 계층 밖)
질문 중 canonical 자동 write · fallback 즉시 승격 · endpoint 에서 승인 처리 · approval UI · backend schema 추가 ·
자동 seed/sync. 이들은 승인형 apply 단계(backend 소유자)와 별도 브랜치의 몫이다.
