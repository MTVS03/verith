import type { SupervisorAnalyzeResponse } from "@/types/supervisor";

import { DEMO_ANALYZE } from "@/features/supervisor/mock-data/demo-analyze";

export type AnalyzeResult = {
  response: SupervisorAnalyzeResponse;
  live: boolean; // true = 실제 supervisor 응답, false = AI 미가동 → 검증된 데모로 폴백
};

// 브라우저에서 same-origin route handler(/api/supervisor/analyze)를 호출한다.
// 그 핸들러가 서버측에서 AI supervisor(:9000)로 포워딩한다(CORS 불필요).
// AI 가 꺼져 있거나 오류면 검증된 데모 결과로 조용히 폴백해 UX 가 끊기지 않게 한다.
export async function analyzeQuery(query: string): Promise<AnalyzeResult> {
  try {
    const res = await fetch("/api/supervisor/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!res.ok) throw new Error(`supervisor ${res.status}`);
    const data = (await res.json()) as SupervisorAnalyzeResponse;
    return { response: data, live: true };
  } catch {
    return { response: { ...DEMO_ANALYZE, original_query: query }, live: false };
  }
}
