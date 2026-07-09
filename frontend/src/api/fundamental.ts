import { backendFetch } from "./backend";

// FundamentalReportEnvelope — { report_id, report }. report 는 저장 시 재구성된 상세 payload
// (fundamental_report + ratios + evidence + interpretation + verification …). 상세 화면은
// report.fundamental_report.report_html(self-contained fragment)을 iframe 으로 띄운다.
export type FundamentalReportEnvelope = {
  report_id: string;
  report: {
    fundamental_report?: { report_html?: string | null } & Record<string, unknown>;
  } & Record<string, unknown>;
};

// 서버측(상세 페이지 = server component)에서 존재 확인 — 없으면 404 로 notFound() 처리.
export async function getFundamentalReport(reportId: string): Promise<FundamentalReportEnvelope> {
  return backendFetch<FundamentalReportEnvelope>(`/api/fundamental/reports/${reportId}`);
}

// DELETE /api/fundamental/reports/{id} → 204. 브라우저에서 백엔드 직접 호출(technical·news·industry 와 동일).
export async function deleteFundamentalReport(reportId: string): Promise<void> {
  await backendFetch<void>(`/api/fundamental/reports/${reportId}`, { method: "DELETE" });
}

// DELETE /api/fundamental/reports → fundamental 리포트 전체 삭제. { deleted: N } 반환.
export async function deleteAllFundamentalReports(): Promise<{ deleted: number }> {
  return backendFetch<{ deleted: number }>(`/api/fundamental/reports`, { method: "DELETE" });
}
