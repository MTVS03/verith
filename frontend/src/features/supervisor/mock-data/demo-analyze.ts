import type { SupervisorAnalyzeResponse } from "@/types/supervisor";

// 실제 supervisor /analyze 를 "LG에너지솔루션 분석해줘"로 돌린 결과(2026-07-09, 5/5 success).
// 백엔드 proxy 가 아직 없어 라이브 호출 대신 이 검증된 실물을 데모로 쓴다(api/supervisor.ts).
export const DEMO_ANALYZE: SupervisorAnalyzeResponse = {
  original_query: "LG에너지솔루션 분석해줘",
  resolution: {
    used_stock_resolver: true,
    used_fallback_lookup: false,
    status: "resolved",
    stock: {
      stock_code: "373220",
      stock_name: "LG에너지솔루션",
      market: "KOSPI",
      source: "canonical_resolver",
      persisted: true,
    },
    candidates: [],
    error: null,
    source: "canonical_resolver",
    persisted: true,
  },
  tasks: [],
  results: [
    { agent_type: "fundamental", status: "success", reason: "stock_resolved", can_run: true, output: null },
    { agent_type: "technical", status: "success", reason: "stock_resolved", can_run: true, output: null },
    { agent_type: "news", status: "success", reason: "stock_resolved", can_run: true, output: null },
    {
      agent_type: "flow",
      status: "success",
      reason: "stock_resolved",
      can_run: true,
      output: { report_id: "619a2a55-de11-417b-a1ca-d43126b8fe1d" },
    },
    { agent_type: "industry", status: "success", reason: "stock_resolved", can_run: true, output: null },
  ],
  request_id: "d640dd66f5d74c838094e0a2591d6399",
  trace_id: "3f4956df753e4854b551cad065c8c89d",
  as_of: "2026-07-09T12:01:12.455107+00:00",
};
