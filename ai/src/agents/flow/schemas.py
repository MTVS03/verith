"""수급(flow) 에이전트 스키마 — 팀 계약 + 내부 상태.

flow-local 위치에 둔다. M1은 flow 혼자 도는 관통선이라 여기서 완결되고,
나중에 팀 통합 시 공유가 필요한 것만 상위로 승격한다(작게 시작, 필요 시 승격).

report_id(UUID) 원리:
  리포트는 백엔드에 저장되고 프론트가 조회한다 → 리포트마다 전역 유일 이름이 필요.
  DB 자동증가(1,2,3…)는 발급 주체가 DB뿐이라, AI 서버가 저장 전엔 자기 ID를 모른다.
  UUID(uuid4)는 128비트 난수라 충돌 확률이 사실상 0 → 누가 어디서 만들어도 유일.
  그래서 생성한 쪽(에이전트)이 태어나는 순간 ID를 붙일 수 있고, 같은 ID가
  로그·검증·저장·조회를 관통한다(상관관계 ID).
"""

from datetime import date
from typing import Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ── 입력 계약 ──────────────────────────────────────────────
class AgentInput(BaseModel):
    """슈퍼바이저가 건네는 질의. 필드는 팀 공통 스키마와 정합 확인 필요."""

    query: str                        # 사용자 원문 (LLM 프롬프트엔 넣지 않음 — 인젝션 방어)
    stock_name: str                   # 예: "삼성전자"
    ticker: Optional[str] = None      # 예: "005930". 없으면 종목명→티커 해석


# ── 검증 게이트 결과 ──────────────────────────────────────
class GateResult(BaseModel):
    """검증 게이트 하나의 결과. 리포트의 검증 배지·체크리스트가 이걸 그대로 렌더.

    passed=False일 때 failures가 empty state 문구의 원료가 된다.
    """

    gate: Literal[1, 2, 3]
    passed: bool
    checks: list[str] = Field(default_factory=list)    # 통과한 검사 서술
    failures: list[str] = Field(default_factory=list)  # 실패 사유


# ── 내부 공유 상태 (LangGraph state) ──────────────────────
class SupplyDemandState(BaseModel):
    """노드들이 읽고 얹는 그릇. 함수 인자가 아니라 state로 흐른다."""

    report_id: UUID = Field(default_factory=uuid4)   # 진입 시 자동 발급
    input: AgentInput

    # collect (+게이트1)
    base_date: Optional[date] = None
    raw: Optional[dict] = None
    gate1: Optional[GateResult] = None
    market: Optional[str] = None   # KIS 대표 시장명 원본(예: 'KOSPI200') — 표시 전용, 검증 대상 아님

    # analyze
    signals: Optional[dict] = None
    gate2: Optional[GateResult] = None

    # explain (+게이트3)
    interpretation: Optional[str] = None
    gate3: Optional[GateResult] = None
    explain_retries: int = 0

    # render
    html: Optional[str] = None


# ── 출력 계약 ──────────────────────────────────────────────
class AgentOutput(BaseModel):
    """팀 계약 후보: {report_id, html, meta}.

    ⚠ 확정 전: 프론트에 recharts가 있어 계약이 HTML이 아니라 구조화 데이터일
    가능성 있음. 그 경우 render 노드만 교체하면 된다(내부가 dict 기반이라).
    """

    report_id: UUID
    html: str
    meta: dict = Field(default_factory=dict)
    # JSON 출구(export/to_json.build_payload) — 선택 필드라 하위 호환.
    # 출력 계약(HTML vs JSON) 확정 시 이 필드의 지위를 팀과 함께 조정한다.
    payload: Optional[dict] = None
