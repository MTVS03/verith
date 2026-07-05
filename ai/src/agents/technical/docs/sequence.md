# 8. 시퀀스 (Sequence)

`docs/sequence.md`

가격/기술적 분석 에이전트의 런타임 흐름을 시간축으로 서술한다. `pipeline.md`가 "노드가 어떤 순서로 있는가"라면, 이 문서는 "각 참여자(에이전트·캐시·KIS·LLM)가 시간에 따라 어떻게 주고받는가"다.

두 시나리오를 다룬다: **정상 흐름**(멀티 타임프레임 반영)과 **KIS 장애 흐름**(복원력).

> **색 규칙** — 보라는 LLM, 청록은 코드, 노란은 검증 분기다.

---

## 1. 정상 흐름 (멀티 타임프레임 반영)

`assets/sequence_normal.png`

참여자: **Top Supervisor · Technical Supervisor · 캐시 · KIS API · LLM**

모든 것이 정상일 때 리포트 하나가 만들어지는 전 과정이다.

### 흐름

1. **Top Supervisor → Technical Supervisor:** 변형 질의 + 티커 전달.
2. **Technical Supervisor → LLM:** 질문 안전 정규화·분석 포커스 정리 요청.
3. **LLM → Technical Supervisor:** normalized_question·analysis_focus 반환.
4. **Technical Supervisor → 캐시:** 과거 봉 조회.
5. **캐시 → Technical Supervisor:** 캐시 히트.
6. **Technical Supervisor → 캐시/KIS:** 일봉·주봉·월봉 캐시를 확인하고, 없거나 갱신이 필요한 타임프레임만 KIS D/W/M으로 각각 호출한다(장중엔 오늘 일봉 우선 갱신).
7. **KIS API → Technical Supervisor:** 타임프레임별 OHLCV 응답.

### 코드 계산 (내부) — LLM 미개입

봉 데이터를 받은 뒤, 다음이 전부 코드 내부에서 일어난다. **LLM이 개입하지 않는다.**
- 일봉·주봉·월봉은 KIS D/W/M 원본 (각각 조회, 리샘플 없음)
- 노드 4: 일봉 기반 지표 (IndicatorBundle 스칼라 — confidence·risk가 소비)
- 노드 5: 국면분류 (일봉 국면 + 주/월봉 추세 계산 + 상위 보정·alignment)
- 노드 6: 종합 / 7: 신뢰도 / 8: 리스크 / 9: 차트

### 해석과 검증 분기

8. **Technical Supervisor → LLM:** 국면 해석 요청 (**확정 라벨·수치를 전달**). LLM은 이 확정값을 받아 문장으로 풀 뿐이다.
9. **LLM → Technical Supervisor:** 해석 문장 반환.

여기서 **검증 ③ 분기(alt)**가 갈린다:
- **[D검증 통과 · 코드 라벨 == LLM 라벨]** → 리포트 확정.
- **[검증 실패]** → 재생성 1회(라벨 강제 주입) → 재생성 문장 반환. **또 실패하면 템플릿 문장으로 폴백.**

10. **Technical Supervisor → Top Supervisor:** 리포트 반환 (JSON).

### 핵심

8번에서 Technical Supervisor가 LLM에 넘기는 것은 **이미 코드가 확정한 라벨·수치**다. LLM은 그걸 문장으로 옮기고, 9번 직후 검증 ③이 "옮기는 과정에서 라벨을 왜곡하지 않았는지"를 잡는다. LLM을 쓰되 검증으로 가두는 구조가 시퀀스 상에서 8→9→검증 분기로 드러난다.

---

## 2. KIS 장애 흐름 (E 복원력)

`assets/sequence_failure.png`

참여자: **기술적 에이전트 · 캐시 · KIS API**

KIS 장애는 D/W/M 중 어느 타임프레임에서 발생했는지에 따라 다르게 착지한다. 흐름이 죽지 않고 안전하게 내려앉는 과정이다.

### 흐름

1. **에이전트 → 캐시:** 일봉·주봉·월봉 캐시 확인.
2. **에이전트 → KIS API:** 없거나 갱신 필요한 타임프레임을 D/W/M으로 호출.
3. 특정 타임프레임 호출 실패 시 최대 3회 재시도(1·2·4초 백오프).

### alt — 타임프레임별 실패 분기

**[일봉(D) 실패 + stale daily 있음]**
4. stale daily로 계산, `data_status=stale_cache` (최신 시세 미반영 표기).

**[일봉(D) 실패 + 캐시 없음]**
5. `data_status=data_limited`. **환각으로 안 채움.**

**[주봉(W)·월봉(M) 실패 + stale W/M 있음]**
6. stale 상위 타임프레임 사용, 최신봉 미반영 표시(보조 안내).

**[주봉(W)·월봉(M) 실패 + 캐시 없음, D 정상]**
7. 일봉 기준 분석은 계속. 해당 상위 추세는 `weekly_trend`/`monthly_trend=unavailable`, `data_status=data_limited`.

### 마무리

8. 확보된 데이터 범위로 지표·국면을 계산한다(안 되는 상위 추세는 unavailable로 둔 채).

### 핵심

두 가지가 이 시퀀스의 요점이다.
- **loop에 상한(최대 3회)이 있어** 무한 재시도가 없다. 정상 흐름 시퀀스의 검증 재생성 루프(1회)와 함께, veriθ의 두 루프 모두 상한이 있다.
- **캐시가 없으면 "환각으로 안 채운다."** 없는 데이터를 그럴듯하게 지어내지 않고 `data_limited`로 정직하게 표기한다. honest scoping이 복원력 레벨에서도 지켜지는 지점이다.

---

## 관련 문서

| 문서 | 담당 |
| --- | --- |
| `pipeline.md` | 노드 구조·순서 (5개 도식) |
| `architecture.md` | E 하네스·저장·슈퍼바이저 구조 |
| `config.md` | 재시도 상수(KIS_MAX_RETRIES·BACKOFF), 캐시 TTL |
| `enums.md` | data_status (normal/stale_cache/data_limited/regime_unavailable) |
