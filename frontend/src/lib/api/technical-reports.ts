/** Technical Report API — /api/technical/reports */

import { apiClient, toApiError } from "./client";
import type {
  TechnicalReportCreateRequest,
  TechnicalReportReadModel,
} from "@/types/technical-report";

export const technicalReportsApi = {
  /**
   * AI 분석 호출 → 검증 → 저장 → read model 반환(201).
   * 422 입력거부 / 502 upstream / 504 timeout 은 ApiError 로 던진다.
   */
  async create(
    payload: TechnicalReportCreateRequest,
  ): Promise<TechnicalReportReadModel> {
    try {
      const { data } = await apiClient.post<TechnicalReportReadModel>(
        "/api/technical/reports",
        payload,
      );
      return data;
    } catch (err) {
      throw toApiError(err);
    }
  },

  /** 단건 조회(상세 화면용). 없으면 not_found ApiError. */
  async get(reportId: string): Promise<TechnicalReportReadModel> {
    try {
      const { data } = await apiClient.get<TechnicalReportReadModel>(
        `/api/technical/reports/${reportId}`,
      );
      return data;
    } catch (err) {
      throw toApiError(err);
    }
  },
};
