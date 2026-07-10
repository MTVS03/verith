import Link from "next/link";
import { notFound } from "next/navigation";

import { getIndustryReport } from "@/api/industry";
import { BackendApiError } from "@/api/backend";
import { IndustryActions } from "@/features/industry/components/industry-actions";
import { IndustryReportView } from "@/features/industry/components/industry-report-view";

export default async function IndustryReportPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = await params;
  // payload(research-report.v1)를 서버에서 받아 React 로 직접 그린다(없으면 404).
  // 예전 iframe(AI HTML) 방식은 dc-runtime 부팅 실패 시 fallback 표만 떠서 폐기 — flow 와 동일한 네이티브 렌더.
  let envelope;
  try {
    envelope = await getIndustryReport(reportId);
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }

  return (
    <div className="min-h-screen bg-[#eceef3] px-4 py-8 font-sans text-[#1e293b] antialiased sm:px-6 lg:px-8">
      <article className="mx-auto w-full max-w-[1120px]">
        {/* Top Brand Bar */}
        <div className="mb-5 flex h-[60px] items-center justify-between rounded-2xl border border-[#e2e8f0] bg-white px-6 shadow-sm print:hidden">
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

        <IndustryActions reportId={reportId} />
        <IndustryReportView payload={envelope.report} />
      </article>
    </div>
  );
}
