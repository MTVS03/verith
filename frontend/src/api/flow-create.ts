// 파이프라인이 브라우저에서 same-origin route handler(/api/flow/reports)를 호출한다.
// news·fundamental 과 같은 save-only — backend 는 AI 를 다시 부르지 않고 supervisor 가 이미 만든
// flow output.payload(storage-spec v1)를 그대로 저장한다.
export type CreatedReport = { report_id: string };

export async function createFlowReport(input: {
  payload: Record<string, unknown>;
  question: string;
}): Promise<CreatedReport> {
  const res = await fetch("/api/flow/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ payload: input.payload, question: input.question }),
  });
  if (!res.ok) throw new Error(`flow create ${res.status}`);
  const data = (await res.json()) as { report_id?: string };
  if (!data.report_id) throw new Error("flow create: missing report_id");
  return { report_id: data.report_id };
}
