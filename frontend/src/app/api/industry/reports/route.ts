import type { NextRequest } from "next/server";

// same-origin 프록시 — 브라우저 → (이 Next route handler) → backend industry create.
// technical 과 동일 계약: backend 가 AI(GraphRAG)를 호출→검증→저장하고 report_id 를 돌려준다.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid json" }, { status: 400 });
  }

  const upstream = await fetch(`${BACKEND_URL}/api/industry/reports`, {
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
