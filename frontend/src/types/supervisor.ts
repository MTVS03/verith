/**
 * Supervisor 계약 — POST /internal/supervisor/analyze
 * 정본: ai/src/api/supervisor.py + ai/src/supervisor/runtime.py(to_response_dict)
 *
 * 자연어 query 하나를 받아 planning + execution 을 흘려 **각 서브에이전트의 리포트**를 돌려준다.
 * 프론트는 results[].output(에이전트가 만든 리포트 JSON/HTML)을 에이전트별로 렌더만 한다.
 */

export type AgentType =
  | "fundamental"
  | "technical"
  | "news"
  | "flow"
  | "industry";

export type AgentStatus = "success" | "failed";

export interface SupervisorResolution {
  used_stock_resolver: boolean;
  used_fallback_lookup: boolean;
  status: string; // resolved | ambiguous | not_found
  stock: {
    stock_code: string;
    stock_name: string;
    market: string | null;
  } | null;
  candidates: unknown[];
  error: string | null;
}

export interface SupervisorTask {
  agent_type: AgentType;
  rewritten_query: string;
  can_run: boolean;
  reason: string;
  context?: unknown;
}

export interface AgentResult {
  agent_type: AgentType;
  status: AgentStatus;
  reason: string | null;
  /** 성공 시 그 에이전트의 리포트 JSON(도메인별 상이). 실패 시 null. */
  output: unknown;
}

export interface SupervisorResponse {
  original_query: string;
  resolution: SupervisorResolution;
  tasks: SupervisorTask[];
  results: AgentResult[];
  request_id: string;
  trace_id: string;
  as_of: string;
}
