import type { NextRequest } from "next/server";

// same-origin 프록시 — 브라우저 → (이 Next route handler, 서버측) → AI supervisor.
// 이렇게 하면 CORS 없이, 백엔드 변경 없이 라이브 supervisor 를 붙일 수 있다.
// 백엔드에 정식 /api/supervisor/analyze proxy 가 생기면 이 URL 만 그쪽으로 돌리면 된다.
const AI_SUPERVISOR_URL =
  process.env.AI_SUPERVISOR_URL ?? "http://localhost:9000/internal/supervisor";

export async function POST(request: NextRequest) {
  let body: { query?: string };
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid json" }, { status: 400 });
  }

  const query = (body.query ?? "").trim();
  if (!query) {
    return Response.json({ error: "query required" }, { status: 400 });
  }

  const upstream = await fetch(`${AI_SUPERVISOR_URL}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ query }),
    cache: "no-store",
  });

  // 상태·본문을 그대로 통과시킨다(성공/부분성공/오류 모두 클라이언트가 판단).
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
