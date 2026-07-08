# Technical Follow-up Answer — 생성 경계 (정본)

`backend/docs/technical_followup_answer_boundary.md`

**"technical follow-up answer 는 누가 만들고, backend 는 어디까지 책임지는가"** 를 잠그는 문서. 팀이 "왜 지금
backend 가 answer 를 안 만드나"를 다시 묻지 않게 하고, 나중에 AI follow-up 생성이 들어올 때의 기준선을 준다.
API 필드/shape 정본은 [`technical_frontend_api_contract.md`](technical_frontend_api_contract.md) — 이 문서는 그 위의
**책임 경계·정책**을 다룬다(모순 없음).

## 1. 개요 (한 줄)
`POST /api/technical/reports/{id}/followups` 는 **caller-provided answer** 정책이다. **backend 는 answer 를
생성하지 않는다** — 검증·저장·parent report snapshot·read/write 정합만 책임진다.

## 2. 현재 아키텍처
```
frontend/상위 ──(question + answer[+meta])──▶ backend POST /followups
                                              backend: 검증 → parent snapshot → row insert → commit
                                              ▲ answer 생성 안 함(LLM 없음)
GET /followups ◀── created_at asc thread (동일 FollowupItem)
```
- backend 에는 **LLM 이 없다**(AIClient 는 HTTP 로 AI 서버의 `analyze_technical`/`analyze_fundamental` 만 호출).
- AI 서버에는 **technical follow-up 전용 endpoint 가 없다**.

## 3. why caller-provided (지금 이게 정답인 이유)
- backend 에 LLM 이 없고, AI 서버에 follow-up 생성 endpoint 도 없다 → backend 가 스스로 답을 만들 수단이 없다.
- follow-up 은 "기존 report 기반 후속 설명"이지 **새 report 생성이 아니다**. answer 생성 주체(상위/supervisor)가
  parent report 결과와 모순 없이 만들고, backend 는 그 답을 **맥락(snapshot)과 함께 저장**하는 얇은 계층이 맞다.
- 이 방식은 지금 바로 동작하고, read/write 저장 경로와 정합이 좋다. (단점: answer 품질이 caller 에 의존.)

## 4. 금지 / 비권장 경로
| 금지 | 이유 |
|---|---|
| backend 가 **자체 LLM 없이 답변 조합문**을 생성 | deterministic string assembly 를 answer 로 공식화하면 품질/책임 경계가 무너진다. backend 는 생성 주체 아님 |
| **`analyze_technical` 를 follow-up answer 용도로 재사용** | 전체 technical report 재생성(KIS+indicator+regime)이라 "기존 report 기반 후속 설명" 경계 위반 + 비용/의미 불일치 |
| follow-up answer 위해 **full technical report 재생성** | 위와 동일 — follow-up 은 새 report 가 아니다 |
| **raw `context_snapshot` 을 프론트 계약으로 직접** 사용 | snapshot 은 내부 저장(future-proof raw). 프론트 계약은 요약 projection(`context`) |

## 5. 현재 request/response 계약 (요약, 상세는 frontend contract)
- **요청 `FollowupCreateRequest`**: `question`(1–1000, 필수)·`answer`(1–50000, **caller required**)·
  `client_session_id?`·`request_id?`·`trace_id?`·`model_name?`.
- **응답 201 `FollowupItem`**(GET list item 과 동일): followup_id·request_id?·question?·answer?·model_name?·
  trace_id?·created_at?·answer_length·`context`(요약). **404**(parent 없음)/**422**(빈·과길이).
- backend 가 저장 시 붙이는 것: parent `context_snapshot`(v1 canonical), created_at.

## 6. 메타 정책 (책임/우선순위)
| 필드 | 책임 | 규칙 |
|---|---|---|
| `question` | caller | required |
| `answer` | **caller (생성 주체)** | required — backend 생성 안 함 |
| `request_id` | caller 우선 | 없으면 backend fallback `fu-<uuid>` |
| `trace_id` | caller (answer 생성 주체) | 없으면 `null`(정직 — 추적 불가 상태를 숨기지 않음) |
| `model_name` | caller (answer 생성 주체) | 없으면 `null` |
| `client_session_id` | caller | optional |
| `context_snapshot` | **backend** | parent report projection 으로 저장(caller 가 주지 않음) |

> `trace_id`/`model_name` 이 `null` = "이 답을 만든 호출/모델 메타가 전달되지 않음". backend 가 지어내지 않는다.

## 7. backend / supervisor / AI 역할 분리표
| 주체 | 책임 | follow-up answer 생성? |
|---|---|---|
| **frontend** | question 입력. 직접 answer 를 만들면 answer(+trace/model meta) 전달 | 경우에 따라 (직접 생성 시) |
| **supervisor / 상위 호출자** | parent report 결과 기반으로 answer 생성 가능. 생성 시 trace_id/model_name 세팅 | ✅ (현재 answer 생성 주체가 될 수 있음) |
| **backend** | parent report 검증·follow-up 저장·parent snapshot·read/write 정합 | ❌ (저장/검증 계층) |
| **AI technical(서버)** | 현재 follow-up 전용 생성 **미제공**(analyze_technical=전체 재생성뿐) | ❌ (미래에 endpoint 생기면 ✅) |

## 8. 미래 AI follow-up 전용 생성 경로 (업그레이드)
```
today:  caller creates answer → POST(question, answer, meta) → backend stores
future: caller sends only question → backend/supervisor calls AI follow-up endpoint
        → generated answer + model/trace meta → 같은 저장 경로(POST 저장·snapshot·read flow) 재사용
```
- **바뀌는 것**: `answer` 를 **optional 로 완화**(미전달 시 backend/supervisor 가 AI follow-up 호출로 채움) + 생성 주체.
- **안 바뀌는 것(future-proof)**: endpoint 경로 · 응답 `FollowupItem` shape · `context_snapshot` 저장 · read flow ·
  메타 우선순위 정책. → **현재 계약은 미래 AI 생성 경로와 충돌하지 않는다.**
- 전제: AI 서버에 "기존 report 기반 후속 설명"용 **follow-up 전용 endpoint**(analyze_technical 재사용 아님)가 별도로
  추가돼야 한다(별도 AI 브랜치).

## 9. FAQ / 협업 관점
- **Q. 프론트가 answer 를 직접 만들어 보내도 되나?** — 된다(현재 정책). trace_id/model_name 을 함께 주면 추적성↑, 없으면 null.
- **Q. supervisor 가 answer 를 만들어 backend 에 저장시키는 건?** — 정확히 의도된 주 경로. supervisor 가 생성 주체, backend 는 저장.
- **Q. trace_id/model_name 이 null 이면?** — 그 답을 만든 호출/모델 메타가 전달 안 됨(backend 가 지어내지 않음).
- **Q. backend 가 나중에 answer 를 만들게 되나?** — backend 자체는 아니다(LLM 없음). AI 서버 follow-up endpoint 를
  backend/supervisor 가 호출하는 형태로 확장된다(§8). 저장 계약은 그대로.
- **Q. 왜 answer 를 지금 backend/AI 가 안 만드나?** — §3(수단 없음) + §4(analyze_technical 재사용은 경계 위반).

## 10. 비대상
follow-up API shape 변경, backend 코드/저장 경로 변경, AI 서버 endpoint 추가, supervisor 구현, answer 품질 개선,
frontend 구현 — 모두 이 문서(경계 정의)의 범위 밖. 실제 AI follow-up 생성 기능은 별도 브랜치(§8 기준선 따름).
