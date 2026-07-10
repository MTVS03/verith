import type { NextRequest } from "next/server";

// same-origin 프록시 — 브라우저 → (이 Next route handler) → backend fundamental save-only.
// backend 는 AI 를 호출하지 않고 supervisor 가 만든 fundamental output 을 저장한다(news 방식).
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid json" }, { status: 400 });
  }

  const upstream = await fetch(`${BACKEND_URL}/api/fundamental/reports/save`, {
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
