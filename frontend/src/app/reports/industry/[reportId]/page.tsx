import Link from "next/link";
import { notFound } from "next/navigation";

import { getIndustryReport } from "@/api/industry";
import { BackendApiError } from "@/api/backend";
import { IndustryActions } from "@/features/industry/components/industry-actions";

export default async function IndustryReportPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = await params;
  // 존재 확인만 서버에서(없으면 404). 실제 화면은 AI 가 만든 완결 HTML 을 iframe 으로 렌더한다.
  let envelope;
  try {
    envelope = await getIndustryReport(reportId);
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
  const question = ((envelope.report?.question as { text?: string } | undefined)?.text) ?? "산업·거시";

  return (
    <div className="min-h-screen bg-[#eceff3] px-4 py-8 font-sans text-[#1e293b] antialiased sm:px-6 lg:px-8">
      <article className="mx-auto w-full max-w-[1120px]">
        {/* Top Brand Bar */}
        <div className="flex h-[60px] items-center justify-between rounded-t-2xl border border-[#e2e8f0] bg-white px-6 shadow-sm">
          <Link href="/" className="flex items-center gap-2">
            <div className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-[#4f46e5] text-[17px] font-bold leading-none text-white">
              θ
            </div>
            <span className="text-[18px] font-bold tracking-tight text-[#0f172a]">
              veri<span className="text-[#4f46e5]">θ</span>
            </span>
            <span className="ml-1 rounded border border-[#e2e8f0] px-1.5 py-0.5 text-[9px] font-bold leading-none text-[#94a3b8]">
              BETA
            </span>
          </Link>
          <span className="text-xs font-bold uppercase tracking-wider text-[#94a3b8]">
            산업·거시 리포트
          </span>
        </div>

        {/* Main Card Wrapper */}
        <div className="rounded-b-2xl border border-t-0 border-[#e2e8f0] bg-white p-6 sm:p-7 md:p-8">
          <IndustryActions reportId={reportId} />

          {/* AI 가 만든 완결 HTML 문서를 iframe 으로 렌더한다.
              sandbox: 스크립트(그래프 인터랙션)·팝업만 허용, same-origin 은 불허(handoff §7).
              dangerouslySetInnerHTML 을 쓰지 않는 이유 = 리포트 자체 CSS/JS 격리. */}
          <iframe
            src={`/api/industry/reports/${reportId}/html`}
            title={`산업 리포트 · ${question}`}
            sandbox="allow-scripts allow-popups"
            className="h-[calc(100vh-220px)] min-h-[640px] w-full rounded-2xl border border-[#f1f5f9] bg-white shadow-sm"
          />
        </div>
      </article>
    </div>
  );
}
