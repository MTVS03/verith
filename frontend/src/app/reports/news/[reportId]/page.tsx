import Link from "next/link";
import { notFound } from "next/navigation";

import { getNewsReport } from "@/api/news";
import { BackendApiError } from "@/api/backend";
import { NewsReportView } from "@/features/news/components/news-report-view";
import { NewsActions } from "@/features/news/components/news-actions";

export default async function NewsReportPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = await params;
  let envelope;
  try {
    envelope = await getNewsReport(reportId);
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
  const report = envelope.report;

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
            {report.subject} 뉴스 리포트
          </span>
        </div>

        {/* Main Card Wrapper */}
        <div className="rounded-b-2xl border border-t-0 border-[#e2e8f0] bg-white p-6 sm:p-7 md:p-8">
          <NewsActions reportId={reportId} />
          <div className="mt-1 grid grid-cols-1 items-start gap-6 lg:grid-cols-[1fr_248px]">
            <div className="min-w-0">
              <NewsReportView report={report} />
            </div>

            {/* Sticky TOC */}
            <aside className="no-print flex flex-col gap-4 lg:sticky lg:top-6">
              <div className="rounded-2xl border border-[#f1f5f9] bg-white p-4 shadow-sm">
                <h4 className="mb-2.5 px-1 text-[11px] font-bold uppercase tracking-wider text-[#94a3b8]">
                  리포트 목차
                </h4>
                <nav className="flex flex-col gap-0.5">
                  {[
                    ["#n-summary", "종합 감성"],
                    ["#n-answer", "AI 분석"],
                    ["#n-volume", "일자별 기사량"],
                    ["#n-events", "주요 이슈"],
                    ["#n-evidence", "근거"],
                  ].map(([href, label]) => (
                    <a
                      key={href}
                      href={href}
                      className="block rounded-lg px-2.5 py-2 text-[12.5px] font-bold text-[#475569] transition-colors hover:bg-slate-50 hover:text-slate-900"
                    >
                      {label}
                    </a>
                  ))}
                </nav>
              </div>
            </aside>
          </div>
        </div>
      </article>
    </div>
  );
}
