/**
 * Research(=supervisor) API — POST /api/research.
 *
 * 프론트는 **오직 백엔드(:8000)** 만 호출한다. 백엔드가 이 요청을 AI supervisor 로 전달하고
 * (그리고 후속으로 DB 저장), 통합 응답(resolution/tasks/results)을 그대로 돌려준다.
 * 프론트는 AI 서비스(:9000)를 직접 호출하지 않는다.
 */

import { apiClient, toApiError } from "./client";
import type { SupervisorResponse } from "@/types/supervisor";

export const supervisorApi = {
  /**
   * 자연어 질의 하나를 백엔드에 보내 각 서브에이전트의 리포트를 받는다.
   * 리포트 생성(AI+KIS+LLM)은 오래 걸릴 수 있으므로 긴 타임아웃을 준다.
   */
  async analyze(query: string): Promise<SupervisorResponse> {
    try {
      const { data } = await apiClient.post<SupervisorResponse>(
        "/api/research",
        { query },
        { timeout: 240_000 },
      );
      return data;
    } catch (err) {
      throw toApiError(err);
    }
  },
};
