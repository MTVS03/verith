// 파이프라인이 브라우저에서 same-origin route handler(/api/fundamental/reports)를 호출한다.
// news 와 같은 save-only — backend 는 AI 를 다시 부르지 않고 supervisor 가 이미 만든
// fundamental output(FundamentalResponse JSON)을 그대로 저장한다. 그래서 output 을 함께 보낸다.
export type CreatedReport = { report_id: string };

export async function createFundamentalReport(input: {
  output: Record<string, unknown>;
  question: string;
}): Promise<CreatedReport> {
  const res = await fetch("/api/fundamental/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ output: input.output, question: input.question }),
  });
  if (!res.ok) throw new Error(`fundamental create ${res.status}`);
  const data = (await res.json()) as { report_id?: string };
  if (!data.report_id) throw new Error("fundamental create: missing report_id");
  return { report_id: data.report_id };
}
