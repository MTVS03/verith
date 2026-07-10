import type { NextRequest } from "next/server";

// same-origin 프록시 — 브라우저 → (이 Next route handler, 서버측) → backend technical create.
// 파이프라인이 technical 리포트를 실제로 저장(POST /api/technical/reports)하고 report_id 를 받는다.
// backend 가 AI 호출→검증→3테이블 저장까지 하므로 여기선 그대로 통과만 시킨다(CORS 불필요).
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid json" }, { status: 400 });
  }

  const upstream = await fetch(`${BACKEND_URL}/api/technical/reports`, {
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
