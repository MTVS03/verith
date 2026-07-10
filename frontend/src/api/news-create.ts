import type { NewsReportModel } from "@/types/news";

// 파이프라인이 브라우저에서 same-origin route handler(/api/news/reports)를 호출한다.
// technical 과 달리 backend 는 AI 를 다시 부르지 않는다 — supervisor 가 이미 만든 news 출력
// (ReportModel)을 그대로 저장(save-only)한다. 그래서 report(=news output)를 함께 보낸다.
export type CreatedReport = { report_id: string };

export async function createNewsReport(input: {
  report: NewsReportModel | Record<string, unknown>;
  question: string;
}): Promise<CreatedReport> {
  const res = await fetch("/api/news/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ report: input.report, question: input.question, intent: "news" }),
  });
  if (!res.ok) throw new Error(`news create ${res.status}`);
  const data = (await res.json()) as { report_id?: string };
  if (!data.report_id) throw new Error("news create: missing report_id");
  return { report_id: data.report_id };
}
