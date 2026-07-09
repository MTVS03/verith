import type { ArchiveListResponse, AgentType } from "@/types/archive";

import { backendFetch } from "./backend";

type ArchiveQuery = {
  agentType?: AgentType;
  clientSessionId?: string;
  stockCode?: string;
  limit?: number;
  offset?: number;
};

export async function getArchiveReports(query: ArchiveQuery = {}): Promise<ArchiveListResponse> {
  const params = new URLSearchParams();
  if (query.agentType) params.set("agent_type", query.agentType);
  if (query.clientSessionId) params.set("client_session_id", query.clientSessionId);
  if (query.stockCode) params.set("stock_code", query.stockCode);
  if (query.limit) params.set("limit", String(query.limit));
  if (query.offset) params.set("offset", String(query.offset));

  const suffix = params.size ? `?${params.toString()}` : "";
  return backendFetch<ArchiveListResponse>(`/api/reports/archive${suffix}`);
}
