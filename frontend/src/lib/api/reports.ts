/** 공통 리포트 보관함 API — GET /api/reports/archive */

import { apiClient, toApiError } from "./client";
import type {
  ArchiveListParams,
  ArchiveListResponse,
} from "@/types/report-archive";

export const reportsApi = {
  /** 보관함 공통 카드 목록(agent_type 필터, created_at DESC). */
  async listArchive(
    params: ArchiveListParams = {},
  ): Promise<ArchiveListResponse> {
    try {
      const { data } = await apiClient.get<ArchiveListResponse>(
        "/api/reports/archive",
        { params },
      );
      return data;
    } catch (err) {
      throw toApiError(err);
    }
  },
};
