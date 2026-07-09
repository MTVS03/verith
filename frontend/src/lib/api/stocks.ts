/** Stock Resolver API — POST /api/stocks/resolve */

import { apiClient, toApiError } from "./client";
import type { StockResolveResponse } from "@/types/stock";

export const stocksApi = {
  /**
   * 사용자 질의에서 종목을 해석한다. resolved/ambiguous/not_found 는 모두 200 으로 온다.
   * 빈 query(422)·DB 장애(503)는 ApiError 로 던진다.
   */
  async resolve(query: string): Promise<StockResolveResponse> {
    try {
      const { data } = await apiClient.post<StockResolveResponse>(
        "/api/stocks/resolve",
        { query },
      );
      return data;
    } catch (err) {
      throw toApiError(err);
    }
  },
};
