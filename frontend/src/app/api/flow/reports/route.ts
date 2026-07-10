import type { NextRequest } from "next/server";

// same-origin 프록시 — 브라우저 → (이 Next route handler) → backend flow save-only.
// backend 는 AI 를 호출하지 않고 supervisor 가 만든 flow payload 를 flow 3테이블에 저장한다.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid json" }, { status: 400 });
  }

  const upstream = await fetch(`${BACKEND_URL}/api/flow/reports/save`, {
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
