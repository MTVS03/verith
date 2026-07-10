import type { AgentType } from "@/types/archive";

// AI supervisor `POST /internal/supervisor/analyze` 응답 계약.
// 출처: ai/src/api/supervisor.py · ai/src/supervisor/README.md
// 프론트는 이 계약을 읽어 질의 창 파이프라인을 그린다(재계산 없음 — 표시만).

export type ResolutionStatus = "resolved" | "not_found" | "error";

// 에이전트 실행 결과 상태 — supervisor 정책(README §정책요약)과 직교하는 축.
// success=output 있음 · skipped=can_run=false로 호출 안 함 · failed=호출 중 예외(부분 성공 격리).
export type AgentRunStatus = "success" | "skipped" | "failed";

export type ResolvedStock = {
  stock_code: string;
  stock_name: string;
  market: string | null;
  source: string | null;
  persisted: boolean;
};

export type SupervisorResolution = {
  used_stock_resolver: boolean;
  used_fallback_lookup: boolean;
  status: ResolutionStatus;
  stock: ResolvedStock | null;
  candidates: unknown[];
  error: string | null;
  source: string | null;
  persisted: boolean;
};

// secret-safe 오류(README): {type, message} — traceback/raw 미노출.
export type AgentError = {
  type: string;
  message: string;
};

export type SupervisorAgentResult = {
  agent_type: AgentType;
  status: AgentRunStatus;
  reason: string | null;
  can_run: boolean;
  // output/context 는 에이전트마다 형태가 달라 느슨하게 둔다(파이프라인 표시엔 report_id만 필요).
  rewritten_query?: string | null;
  context?: Record<string, unknown> | null;
  output?: Record<string, unknown> | null;
  error?: AgentError | null;
};

export type SupervisorAnalyzeResponse = {
  original_query: string;
  resolution: SupervisorResolution;
  tasks: unknown[];
  results: SupervisorAgentResult[];
  request_id: string;
  trace_id: string;
  as_of: string;
};

export type SupervisorAnalyzeRequest = {
  query: string;
};
