// 파이프라인이 브라우저에서 same-origin route handler(/api/industry/reports)를 호출한다.
// 그 핸들러가 backend 로 포워딩해 실제 저장(AI GraphRAG 호출→검증→저장)을 수행하고 report_id 를 돌려준다.
// technical 과 동일 방식(backend 재호출) — industry 는 supervisor 출력을 save-only 로 받는 경로가 없다.
export type CreatedReport = { report_id: string };

export async function createIndustryReport(input: {
  question: string;
}): Promise<CreatedReport> {
  const res = await fetch("/api/industry/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ question: input.question }),
  });
  if (!res.ok) throw new Error(`industry create ${res.status}`);
  const data = (await res.json()) as { report_id?: string };
  if (!data.report_id) throw new Error("industry create: missing report_id");
  return { report_id: data.report_id };
}
