import { backendFetch } from "./backend";

// flow payload(storage-spec v1) — 상세 화면이 JSON 에서 다시 그린다(HTML 저장 안 함).
export type FlowStrength = { ratio: number; strong: boolean };
export type FlowConsecutive = { days: number; signal: boolean };
export type FlowPersistence = { sum_5: number; sum_20: number; consistent: boolean };
export type FlowPriceRow = {
  date: string;
  close: number;
  change: number;
  change_rate: number;
  volume: number;
  frgn_qty: number | null;
  inst_qty: number | null;
};
export type FlowOwnershipRow = { date: string; ratio: number };
export type FlowGate = { gate?: number; passed: boolean; checks: string[]; failures: string[] };

export type FlowPayload = {
  version: number;
  report_id: string;
  trace_id: string | null;
  data_status: string | null;
  meta: { stock_name: string | null; ticker: string | null; market: string | null; base_date: string | null };
  signals: {
    alignment?: string;
    strength?: Record<string, FlowStrength>;
    consecutive?: Record<string, FlowConsecutive>;
    persistence?: Record<string, FlowPersistence>;
    inst_detail?: Record<string, number> | null;
    price_daily?: FlowPriceRow[] | null;
    ownership?: FlowOwnershipRow[] | null;
    daily?: Array<Record<string, number | string>> | null;
  } | null;
  verification: {
    gate1?: FlowGate | null;
    gate2?: FlowGate | null;
    gate3?: FlowGate | null;
    outcome?: string | null;
    regen_count?: number | null;
  } | null;
  interpretation: string | null;
  interpretation_meta: { source: string | null; provider: string | null; model: string | null } | null;
};

export type FlowReportEnvelope = { report_id: string; report: FlowPayload };

export async function getFlowReport(reportId: string): Promise<FlowReportEnvelope> {
  return backendFetch<FlowReportEnvelope>(`/api/flow/reports/${reportId}`);
}

export async function deleteFlowReport(reportId: string): Promise<void> {
  await backendFetch<void>(`/api/flow/reports/${reportId}`, { method: "DELETE" });
}

// DELETE /api/flow/reports → flow 리포트 전체 삭제. { deleted: N } 반환.
export async function deleteAllFlowReports(): Promise<{ deleted: number }> {
  return backendFetch<{ deleted: number }>(`/api/flow/reports`, { method: "DELETE" });
}
