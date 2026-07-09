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

// DELETE /api/technical/reports/{id} → 204. DB 에서 리포트 삭제(하드 delete).
export async function deleteTechnicalReport(reportId: string): Promise<void> {
  await backendFetch<void>(`/api/technical/reports/${reportId}`, { method: "DELETE" });
}

// DELETE /api/technical/reports → technical 리포트 전체 삭제. { deleted: N } 반환.
export async function deleteAllTechnicalReports(): Promise<{ deleted: number }> {
  return backendFetch<{ deleted: number }>(`/api/technical/reports`, { method: "DELETE" });
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
