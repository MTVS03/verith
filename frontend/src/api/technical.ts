import type {
  TechnicalReportFollowupsReadModel,
  TechnicalReportReadModel,
  TechnicalTraceDetailReadModel,
} from "@/types/technical";

import { backendFetch } from "./backend";

// includeCharts=true → `?include=charts` 로 차트 full payload(charts_full)까지 1 JSON 으로 받는다(상세용).
// 목록 등은 includeCharts 없이 호출 → 메타만·가볍게. (전용 /charts 엔드포인트는 폐지됨.)
export async function getTechnicalReport(
  reportId: string,
  opts?: { includeCharts?: boolean },
): Promise<TechnicalReportReadModel> {
  const qs = opts?.includeCharts ? "?include=charts" : "";
  return backendFetch<TechnicalReportReadModel>(`/api/technical/reports/${reportId}${qs}`);
}

export async function getTechnicalTrace(reportId: string): Promise<TechnicalTraceDetailReadModel> {
  return backendFetch<TechnicalTraceDetailReadModel>(`/api/technical/reports/${reportId}/trace`);
}

export async function getTechnicalFollowups(
  reportId: string,
): Promise<TechnicalReportFollowupsReadModel> {
  return backendFetch<TechnicalReportFollowupsReadModel>(
    `/api/technical/reports/${reportId}/followups`,
  );
}
