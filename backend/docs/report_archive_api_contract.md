# Report Archive — 공통 보관함 목록 API 계약 (정본)

`backend/docs/report_archive_api_contract.md`

프론트 "리포트 보관함" 화면이 여러 agent 리포트를 **하나의 공통 카드 리스트**로 렌더하기 위한 목록 API.
agent 별 상세 read model 과 **분리**된 얇은 view model 이다(raw payload 미노출). 상단 필터는 **`agent_type`**
기준이며, 산업/테마 **category/tag 는 이 계약 범위 밖**이다.

## Endpoint
`GET /api/reports/archive` — **created_at DESC**.
| query | 설명 |
|---|---|
| `agent_type?` | `technical`\|`fundamental`\|`news`\|`flow`\|`industry` (상단 탭 필터) |
| `client_session_id?` | 선택 필터 |
| `stock_code?` | 선택 필터 |
| `limit` | 1–100(기본 20) |
| `offset` | ≥0(기본 0) |

> 기존 cross-agent `GET /api/reports`(raw summary 인덱스)와 **별도**다. 보관함 카드용은 이 archive endpoint 를 쓴다.

## 응답 `ArchiveListResponse`
```jsonc
{ "items": [ {
    "report_id": "uuid",              // 상세 리포트 id(agent_report_id)
    "agent_type": "technical",
    "stock": { "stock_code": "005930", "stock_name": "삼성전자", "market": "KOSPI" },  // canonical 조인
    "card": {
      "title": "삼성전자 기술 리포트",
      "summary": "단기 박스권이지만 추세 훼손은 제한적입니다.",   // ≤160자 clip
      "badge_label": "Conf", "badge_value": "84%", "badge_tone": "green",
      "meta_primary": "neutral",       // final_regime(또는 directional_bias)
      "meta_secondary": "2026-07-09"   // created_at date
    },
    "status": { "data_status": "normal" },
    "meta": { "created_at": "…Z", "as_of": "…Z", "detail_url": "/api/technical/reports/{id}" }
  } ], "total": 42, "limit": 20, "offset": 0 }
```

## 공통 카드 매핑 (agent_reports 공통 인덱스 projection)
모든 agent 공통 필드 + `summary`(JSONB)에서 조립(계산 재실행 없음, raw 미노출):
| 카드 필드 | 출처 |
|---|---|
| `title` | `stock_name`(canonical 우선) + agent_type 라벨(기술/재무/뉴스/수급/산업 리포트) |
| `summary` | `answer_text`(≤160자 clip) |
| `badge_label`/`badge_value` | `summary.confidence` 있으면 `"Conf"`/`"NN%"`, 없으면 `null` |
| `badge_tone` | `data_status`(limited/unavailable→`amber`) + `summary.signal_score`(>0.1 `green`, <−0.1 `red`, else `neutral`) |
| `meta_primary` | `summary.final_regime` (또는 `directional_bias`) |
| `meta_secondary` | `created_at` 날짜 |
| `status.data_status` | `data_status` |
| `meta.detail_url` | agent_type 별 상세 경로(technical/fundamental/news 매핑, 그 외 `null`) |

## reference / 확장
- **이번 구현 = technical reference.** agent_reports 를 쓰는 다른 agent(fundamental/news/flow/industry)도 **동일 카드
  shape** 로 자동 매핑된다(agent_reports 에 row 가 있으면). `summary` JSONB 가 얕은 agent 는 badge/meta_primary 가
  `null` 로 내려갈 수 있다(shape 안정).
- `title`/`summary`/`badge`/`meta` 는 **느슨하게** 뒀다 — agent 별 값이 달라도 카드 계약이 깨지지 않는다.
- **category/tag(산업·테마 분류)는 범위 밖.** 필터는 agent_type 만.
- one_line_summary/directional_bias/verification_warning 등 **상세 전용 값은 detail endpoint** 에서
  ([`technical_frontend_api_contract.md`](technical_frontend_api_contract.md)). archive 는 카드용 얇은 값만.

## 비대상
프론트 UI, category/tag 테이블, 검색/복합필터, agent 상세 통일, migration — 범위 밖.
