import type { NextRequest } from "next/server";

// same-origin 프록시 — iframe(브라우저) → (이 Next route handler) → backend industry html.
// industry 상세는 AI 가 만든 완결 HTML 문서를 iframe 으로 띄운다(React 컴포넌트 아님).
// same-origin 으로 받아야 iframe 이 CORS/X-Frame 제약 없이 로드한다(handoff §7).
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await params;
  const autoprint = new URL(request.url).searchParams.get("autoprint") === "1";
  const upstream = await fetch(
    `${BACKEND_URL}/api/industry/reports/${encodeURIComponent(reportId)}/html`,
    { headers: { Accept: "text/html" }, cache: "no-store" },
  );

  let body = await upstream.text();
  // 422(payload 손상)·404 는 그대로 전달한다 — 빈 iframe 대신 상태를 드러낸다(handoff §5).
  const contentType = upstream.headers.get("content-type") ?? "text/html; charset=utf-8";
  // autoprint=1(=PDF 다운로드 버튼이 새 탭으로 열 때) 이면 로드 후 인쇄창을 자동으로 띄운다.
  if (autoprint && upstream.ok && contentType.includes("text/html")) {
    const script =
      `<script>window.addEventListener('load',function(){setTimeout(function(){window.print();},300);});</script>`;
    body = body.includes("</body>") ? body.replace("</body>", `${script}</body>`) : body + script;
  }
  return new Response(body, {
    status: upstream.status,
    headers: { "Content-Type": contentType },
  });
}
