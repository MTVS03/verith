import { backendFetch } from "./backend";

// research-report.v1 payload(요약만) — 상세 존재 확인용. 렌더는 iframe(html 프록시)이 담당한다.
export type IndustryReportEnvelope = {
  report_id: string;
  report: Record<string, unknown>;
};

// 서버측(상세 페이지 = server component)에서 존재 확인 — 없으면 404 로 notFound() 처리.
// 실제 화면은 iframe 이 /api/industry/reports/{id}/html 로 렌더한다.
export async function getIndustryReport(reportId: string): Promise<IndustryReportEnvelope> {
  return backendFetch<IndustryReportEnvelope>(`/api/industry/reports/${reportId}`);
}

// DELETE /api/industry/reports/{id} → 204. 브라우저에서 백엔드 직접 호출(backend CORS 허용, technical·news 와 동일).
export async function deleteIndustryReport(reportId: string): Promise<void> {
  await backendFetch<void>(`/api/industry/reports/${reportId}`, { method: "DELETE" });
}

// DELETE /api/industry/reports → industry 리포트 전체 삭제. { deleted: N } 반환.
export async function deleteAllIndustryReports(): Promise<{ deleted: number }> {
  return backendFetch<{ deleted: number }>(`/api/industry/reports`, { method: "DELETE" });
}
