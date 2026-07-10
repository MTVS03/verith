// 파이프라인이 브라우저에서 same-origin route handler(/api/technical/reports)를 호출한다.
// 그 핸들러가 backend 로 포워딩해 실제 저장(AI 호출→검증→3테이블)을 수행하고 report_id 를 돌려준다.
export type CreatedReport = { report_id: string };

export async function createTechnicalReport(input: {
  ticker: string;
  query: string;
}): Promise<CreatedReport> {
  const res = await fetch("/api/technical/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ ticker: input.ticker, query: input.query }),
  });
  if (!res.ok) throw new Error(`technical create ${res.status}`);
  const data = (await res.json()) as { report_id?: string };
  if (!data.report_id) throw new Error("technical create: missing report_id");
  return { report_id: data.report_id };
}
