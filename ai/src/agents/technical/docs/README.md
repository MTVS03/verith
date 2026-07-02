# veriθ 가격/기술적 분석 에이전트 — 설계 문서

`docs/README.md`

veriθ ② **가격/기술적 분석 에이전트**의 설계 문서 인덱스다. 이 에이전트는 종목의 기술적 국면·신호·리스크를 산출하되, **regime·signal_score·confidence·risk를 전부 코드가 확정하고 LLM은 문장으로 풀기만** 한다. 이 "LLM을 썼지만 검증으로 가뒀다"가 설계의 축이다.

> **핵심 가치 — honest scoping.** 시스템이 실제로 하는 것만 정직하게 표현한다. 네이밍·프레이밍은 마케팅이 아니라 기술 결정이다. "사라/팔라"가 아니라 "관찰된다/보인다".

---

## 처음이면 여기부터

**`architecture.md`를 먼저 읽는다.** 슈퍼바이저 관계·A~E층·저장구조를 한 장으로 조망하는 문서라, 나머지 문서가 어디에 끼워지는지 지도를 준다. 그다음 용어(glossary)부터 세부로 내려간다.

권장 읽는 순서 (큰 그림 → 세부):

```
architecture → glossary → regime_rules → enums → contracts → config
   (조망)        (용어)      (규칙)        (값)      (계약)      (설정)
```

규칙·값·계약을 파악한 뒤, 흐름과 시나리오를 보고 싶으면 `pipeline.md`(도식) → `sequence.md`(시간축) → `usecase.md`(시나리오 T1~T6) 순으로 읽는다.

구현 직전 단계(LLM 프롬프트·검증·DB·화면·API)를 볼 때는 `prompts.md`(LLM 계약) → `test_plan.md`(검증) → `schema.md`(DB) → `trace_schema.md`(실행 로그) → `frontend_mapping.md`(화면 매핑) → `api_spec.md`(HTTP API) 순으로 읽는다.

실제 코드 착수 전에는 `kis_mapping.md`(KIS 연동)와 `implementation_plan.md`(모듈↔문서 매핑·개발 순서)를 본다.

파일 앞 번호(1~18)는 **작성·관리 순서**일 뿐 읽는 순서가 아니다. 번호는 상호 참조·변경 이력 관리를 위해 유지한다.

---

## 문서 목록

| 파일 | 담당 | 한 줄 요약 |
| --- | --- | --- |
| `architecture.md` (6) | 아키텍처 | 두 슈퍼바이저·A~E층·저장구조(PostgreSQL/Redis) 통합 조망 |
| `glossary.md` (1) | 용어 정의 | 핵심 산출물 용어, 헷갈리는 축(signal_score vs confidence 등) 구분 |
| `regime_rules.md` (2) | 국면 판정 규칙 | 일봉 6종 + 멀티프레임 보정 + 보조 판정 정의. 검증 ② 기준 |
| `enums.md` (3) | 열거값 | 코드값(영문) ↔ 표시 라벨(한글). 코드·DB·프론트 단일 기준 |
| `contracts.md` (4) | 입출력 계약 | 입력 스키마 1개 + 출력 JSON 1개, JSON↔ERD 매핑 |
| `config.md` (5) | 설정값 | 구조는 코드, 수치는 config. 전부 MVP v1 기준값 |
| `pipeline.md` (7) | 파이프라인 | 5개 도식(A~E층·성공·멀티프레임·장애·분기) 서술 |
| `sequence.md` (8) | 시퀀스 | 정상 흐름·KIS 장애 흐름 시간축 서술 |
| `usecase.md` (9) | 유스케이스 | 시나리오 T1~T6, 각 검증(①②③)·가드(E1·E2)와 연결 |
| `prompts.md` (10) | LLM 프롬프트 계약 | 질문 정규화·포커스 정리·국면해석 + 재생성. 금지/허용 표현, 검증 ③ 원문 |
| `test_plan.md` (11) | 테스트 계획 | 검증 ①②③ + 계약·복원력·trace. 검증 ③은 키워드 매칭 |
| `schema.md` (12) | DB 스키마 | PostgreSQL 6테이블 DDL + Redis 캐시 + contracts→DB 매핑 |
| `trace_schema.md` (13) | Trace 스키마 | 실행 관측 로그(JSONL). 노드 코드값·검증·예외 추적 |
| `frontend_mapping.md` (14) | 프론트 매핑 | JSON 필드 → 화면 섹션·표시 라벨·예외 렌더링 |
| `api_spec.md` (15) | API 명세 | HTTP 엔드포인트(생성/조회/trace), 식별자 규칙, 예외=정상응답 |
| `implementation_plan.md` (16) | 구현 계획 | 모듈↔문서 매핑, 폴더 구조, 개발 순서, MVP 제외 범위 |
| `kis_mapping.md` (17) | KIS 매핑 | KIS API 연동, 원본→내부 OHLCV 필드 매핑, 종목 allowlist |
| `chart_annotation_spec.md` (18) | 차트 Annotation | 차트 overlays·subcharts·annotations 계산·렌더링 기준 (1d 장중 차트는 Beta) |

---

## 어디를 볼지 (질문별 길잡이)

| 알고 싶은 것 | 볼 문서 |
| --- | --- |
| 전체 구조·슈퍼바이저·저장이 어떻게 맞물리나 | `architecture.md` |
| 이 용어가 무슨 뜻인가 / 두 개념이 어떻게 다른가 | `glossary.md` |
| 국면(regime)을 어떤 규칙으로 정하나 | `regime_rules.md` |
| 이 필드에 어떤 값이 들어가나 / 코드값·라벨 대응 | `enums.md` |
| 입력·출력 JSON 모양 / DB 어느 컬럼에 저장되나 | `contracts.md` |
| 임계값·가중치·기간 같은 수치가 얼마인가 | `config.md` |
| alignment_flag 한글("정합/역행")이 어떤 코드값인가 | `architecture.md` §6.1 |
| LLM에 무엇을 주고 무엇을 금지하나 | `prompts.md` |
| 검증 ①②③을 어떻게 테스트하나 | `test_plan.md` |
| DB 테이블·컬럼·DDL / Redis 캐시 구조 | `schema.md` |
| 실행 과정을 어떻게 추적·디버깅하나 | `trace_schema.md` |
| JSON을 화면에 어떻게 뿌리나 / 표시 라벨 | `frontend_mapping.md` |
| 어느 HTTP 엔드포인트로 호출·조회하나 | `api_spec.md` |
| KIS에서 시세를 어떻게 받나 / MVP 종목 범위 | `kis_mapping.md` |
| 차트에 무슨 신호를 어떻게 그리나 / 1일 탭 | `chart_annotation_spec.md` |
| 어느 모듈부터 어떤 순서로 개발하나 | `implementation_plan.md` |

---

## 변경 규약

값이나 구조를 바꿀 때는 **문서를 먼저 고치고 코드·backend에 반영**한다. 세 계층이 항상 일치해야 한다.

- **열거값 추가·변경:** `enums.md` 먼저 → 코드·DB·프론트.
- **계약 변경(JSON 필드·구조):** `contracts.md` → `enums.md` → 코드·backend.
- **DB 컬럼명·저장 구조 변경:** `schema.md` 먼저 (DB 이름의 최종 기준) → contracts 매핑 반영 → 코드·backend.
- **엔드포인트·HTTP status·timeout 변경:** `api_spec.md` 먼저 → 관련 문서 → 코드.
- **수치 조정:** `config.md`만 고침 (구조는 코드에 있어 안 바뀜). 관련 검증 테스트 기대값도 함께 검토.
- **코드값은 불변(snake_case).** 한 번 정하면 안 바꾼다(DB 마이그레이션·API 호환). 한글 라벨은 UI 사정으로 바꿔도 된다(정본은 `enums.md`).

---

## 도식 (assets/)

설계 그림은 `assets/`에 있다. 읽는 순서: 전체 구조 → 정상 흐름 → 멀티프레임 상세 → 장애·검증 → 예외·분기. 색 규칙 공통 — **보라=LLM, 청록=코드.** 각 도식에 대한 서술은 `pipeline.md`·`sequence.md`가 담당한다.

| 파일 | 내용 | 대응 문서 |
| --- | --- | --- |
| `pipeline_ae_layers.png` | ① A~E층 파이프라인 조망 | pipeline §1 |
| `pipeline_success.png` | ② 성공 경로 (노드 10개) | pipeline §2 |
| `node4_5_multiframe.png` | ③ 노드 4·5 멀티 타임프레임 상세 | pipeline §3 |
| `pipeline_de_failure.png` | ④ D·E 층 실패·검증 3층 | pipeline §4 |
| `pipeline_branches.png` | ⑤ 분기·루프 최종 흐름 | pipeline §5 |
| `sequence_normal.png` | 시퀀스 · 정상 흐름 | sequence §1 |
| `sequence_failure.png` | 시퀀스 · KIS 장애 흐름 | sequence §2 |

### ✅ 도식 이미지 (assets) — 최신 설계 반영 완료

7개 도식 전부 최신 규약(D/W/M 직접 호출, 노드명 확정, 월봉 우선 보정, "최신 시세 미반영")으로 재생성했다. 각 도식은 SVG(수정용)와 PNG(제출용, 폭 1600px) 두 형식으로 `assets/`에 있다.

- ✅ `node4_5_multiframe` — resampler 박스 제거 → D/W/M 직접 호출. 월봉 우선·주봉 대체·중립 국면 예외 반영.
- ✅ `pipeline_success` — 노드2 "전략 선택" → "분석 포커스 정리", "리샘플" → "KIS 직접 호출", "기본 5개 지표(데이터 부족 시 계산 가능분만)".
- ✅ `pipeline_ae_layers` — 노드1·2 이름 최신화, "일봉 5지표 + 주/월 추세 (D/W/M 직접 호출)".
- ✅ `pipeline_branches` — "전략선택" → "분석 포커스", "KIS 일봉" → "KIS D/W/M", "어제 종가·미반영" → "최신 시세 미반영", "관망" → "중립".
- ✅ `pipeline_de_failure` — "KIS 일봉 호출" → "KIS D/W/M", "상승 초입" → "상승 전환 관찰"(확정 라벨), 타임프레임별 폴백.
- ✅ `sequence_normal` — "일봉→주/월 리샘플" 제거 → D/W/M 직접 호출, "종목·기간·지표 반환" → normalized_question·analysis_focus.
- ✅ `sequence_failure` — "오늘 일봉 실패"만 → D/W/M 타임프레임별 4개 분기(D실패+stale / D실패+캐시없음 / W·M실패+stale / W·M실패+캐시없음), "종가 미반영" → "최신 시세 미반영".
