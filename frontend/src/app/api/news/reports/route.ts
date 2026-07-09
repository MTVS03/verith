import type { NextRequest } from "next/server";

// same-origin 프록시 — 브라우저 → (이 Next route handler, 서버측) → backend news save.
// backend 는 AI 를 호출하지 않고 받은 ReportModel JSON 을 news_reports 에 저장한다(save-only).
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid json" }, { status: 400 });
  }

  const upstream = await fetch(`${BACKEND_URL}/news/reports`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
