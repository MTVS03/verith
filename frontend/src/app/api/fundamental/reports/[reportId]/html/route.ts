import type { NextRequest } from "next/server";

// same-origin 프록시 — iframe(브라우저) → (이 Next route handler) → backend fundamental report.
// industry 와 달리 AI render 를 호출하지 않는다: fundamental 은 report_html(self-contained
// fragment)을 저장 시 그대로 담아두므로, 저장된 report 에서 꺼내 완결 문서로 감싸 돌려준다.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

function wrapFragment(fragment: string, autoprint: boolean): string {
  // report_html 은 자체 <style> 을 포함한 fragment 다. iframe 이 독립 렌더하도록 최소 문서로 감싼다.
  // autoprint=1 이면(=PDF 다운로드 버튼이 새 탭으로 열 때) 로드 후 인쇄창을 자동으로 띄운다.
  const printScript = autoprint
    ? `<script>window.addEventListener('load',function(){setTimeout(function(){window.print();},250);});</script>`
    : "";
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0;padding:24px;background:#fff;font-family:'Pretendard',system-ui,-apple-system,sans-serif;}</style></head><body>${fragment}${printScript}</body></html>`;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await params;
  const autoprint = new URL(request.url).searchParams.get("autoprint") === "1";
  const upstream = await fetch(
    `${BACKEND_URL}/api/fundamental/reports/${encodeURIComponent(reportId)}`,
    { headers: { Accept: "application/json" }, cache: "no-store" },
  );

  if (!upstream.ok) {
    // 404 등 상태를 그대로 드러낸다(빈 iframe 대신).
    return new Response(`report not available (${upstream.status})`, {
      status: upstream.status,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }

  const envelope = (await upstream.json()) as {
    report?: { fundamental_report?: { report_html?: string | null } };
  };
  const html = envelope.report?.fundamental_report?.report_html;
  if (!html) {
    return new Response("이 리포트에는 표시할 HTML 이 없습니다.", {
      status: 404,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }

  return new Response(wrapFragment(html, autoprint), {
    status: 200,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}
