import type { NewsReportEnvelope } from "@/types/news";

import { backendFetch } from "./backend";

// 서버측(상세 페이지 = server component)에서 backend 로 직접 조회 — CORS 불필요.
// 경로는 backend news 라우터 prefix 그대로 `/news/reports/{id}` (technical 과 달리 /api 없음).
export async function getNewsReport(reportId: string): Promise<NewsReportEnvelope> {
  return backendFetch<NewsReportEnvelope>(`/news/reports/${reportId}`);
}

// DELETE /news/reports/{id} → 204. 브라우저에서 백엔드 직접 호출(backend CORS 허용, technical 삭제와 동일).
export async function deleteNewsReport(reportId: string): Promise<void> {
  await backendFetch<void>(`/news/reports/${reportId}`, { method: "DELETE" });
}

// DELETE /news/reports → news 리포트 전체 삭제. { deleted: N } 반환.
export async function deleteAllNewsReports(): Promise<{ deleted: number }> {
  return backendFetch<{ deleted: number }>(`/news/reports`, { method: "DELETE" });
}
