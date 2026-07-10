import Link from "next/link";
import { notFound } from "next/navigation";

import { getFlowReport } from "@/api/flow";
import { BackendApiError } from "@/api/backend";
import { FlowActions } from "@/features/flow/components/flow-actions";
import { FlowReportView } from "@/features/flow/components/flow-report-view";

export default async function FlowReportPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = await params;
  let envelope;
  try {
    envelope = await getFlowReport(reportId);
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }

  // 배경·카드 구성은 flow 목업(flow_sample) 디자인 언어: #F2F4F6 위에 흰 카드들.
  return (
    <div className="min-h-screen bg-[#F2F4F6] px-4 py-8 font-sans antialiased sm:px-6 lg:px-8">
      <article className="mx-auto w-full max-w-[1200px]">
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
          <span className="text-xs font-bold uppercase tracking-wider text-[#94a3b8]">수급·자금흐름 리포트</span>
        </div>

        <FlowActions reportId={reportId} />
        <FlowReportView payload={envelope.report} />
      </article>
    </div>
  );
}
