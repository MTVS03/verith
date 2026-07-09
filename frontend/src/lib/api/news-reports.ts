/** News Report API — GET /api/news/reports/{id} */

import { apiClient, toApiError } from "./client";
import type { NewsReportEnvelope } from "@/types/news-report";

export const newsReportsApi = {
  /** 단건 조회 — { report_id, report }. report 는 ai ReportModel JSON 원본. */
  async get(reportId: string): Promise<NewsReportEnvelope> {
    try {
      const { data } = await apiClient.get<NewsReportEnvelope>(
        `/news/reports/${reportId}`,
      );
      return data;
    } catch (err) {
      throw toApiError(err);
    }
  },
};
