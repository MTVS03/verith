import { getTechnicalFollowups, getTechnicalReport, getTechnicalTrace } from "@/api/technical";
import { TechnicalChartPanel } from "@/features/technical/components/technical-chart-panel";
import { TechnicalFollowups } from "@/features/technical/components/technical-followups";
import { TechnicalHero } from "@/features/technical/components/technical-hero";
import { TechnicalSignalRiskGrid } from "@/features/technical/components/technical-signal-risk-grid";
import { TechnicalSummarySections } from "@/features/technical/components/technical-summary-sections";
import { TechnicalTraceDrawer, TechnicalTimeline } from "@/features/technical/components/technical-trace-drawer";
import { applyLgEnergyDemoOverrides } from "@/features/technical/mock-data/demo-overrides";

export const dynamic = "force-dynamic";

const DEMO_REPORT_ID = "eb59303e-5f8d-4b1b-8b15-e145839a9861";

export default async function TechnicalDemoPage() {
  const [rawReport, trace, followups] = await Promise.all([
    getTechnicalReport(DEMO_REPORT_ID, { includeCharts: true }),
    getTechnicalTrace(DEMO_REPORT_ID),
    getTechnicalFollowups(DEMO_REPORT_ID),
  ]);
  const report = applyLgEnergyDemoOverrides(rawReport);
  const charts = report.charts_full ?? rawReport.charts_full ?? null;

  return (
    <div className="min-h-screen bg-[#eceff3] py-8 px-4 sm:px-6 lg:px-8 font-sans antialiased text-[#1e293b]">
      <article className="mx-auto w-full max-w-[1120px]">
        {/* Top Brand Bar */}
        <div className="h-[60px] bg-white border border-[#e2e8f0] rounded-t-2xl flex items-center justify-between px-6 shadow-sm">
          <div className="flex items-center gap-2">
            <div className="w-[30px] h-[30px] rounded-lg bg-[#4f46e5] grid place-items-center text-white font-bold text-[17px] leading-none">
              θ
            </div>
            <span className="text-[18px] font-bold tracking-tight text-[#0f172a]">
              veri<span className="text-[#4f46e5]">θ</span>
            </span>
            <span className="ml-1 text-[9px] font-bold text-[#94a3b8] border border-[#e2e8f0] rounded px-1.5 py-0.5 leading-none">
              BETA
            </span>
          </div>
          <span className="text-xs font-bold tracking-wider text-[#94a3b8] uppercase">
            {report.stock.stock_name} 기술 리포트 데모
          </span>
        </div>

        {/* Main Card Wrapper */}
        <div className="bg-white border border-[#e2e8f0] border-t-0 rounded-b-2xl p-6 sm:p-7 md:p-8">
          {/* Header section & metadata */}
          <TechnicalHero report={report} charts={charts} />

          {/* Main content grid */}
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_248px] gap-6 items-start mt-6">
            {/* Left column */}
            <div className="flex flex-col gap-5 min-w-0">
              <TechnicalSummarySections report={report} />
              {charts && <TechnicalChartPanel charts={charts} />}
              <TechnicalSignalRiskGrid report={report} />
              <TechnicalTraceDrawer trace={trace} report={report} />
              <div className="p-4 border border-[#f1f5f9] rounded-2xl bg-[#f8fafc] flex items-center gap-2.5">
                <div className="text-[#10b981] flex-shrink-0">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                </div>
                <p className="text-[13px] text-[#475569]">
                  이 리포트는 기술적 신호 종합이며 <b className="text-[#0f172a] font-semibold">투자 권유가 아닙니다.</b> 모든 수치는 KIS 시세에 연결되어 검증됩니다.
                </p>
              </div>
            </div>

            {/* Right column sticky sidebar */}
            <aside className="lg:sticky lg:top-6 flex flex-col gap-4">
              <div className="border border-[#f1f5f9] rounded-2xl p-4 shadow-sm bg-white">
                <h4 className="text-[11px] font-bold text-[#94a3b8] uppercase tracking-wider mb-2.5 px-1">리포트 목차</h4>
                <nav className="flex flex-col gap-0.5">
                  <a href="#a-summary" className="block px-2.5 py-2 text-[12.5px] font-bold text-[#475569] hover:bg-slate-50 hover:text-slate-900 rounded-lg transition-colors">
                    신호 종합 (Signal)
                  </a>
                  <a href="#a-flow" className="block px-2.5 py-2 text-[12.5px] font-bold text-[#475569] hover:bg-slate-50 hover:text-slate-900 rounded-lg transition-colors">
                    신호 흐름 요약 (AI 분석)
                  </a>
                  <a href="#a-chart" className="block px-2.5 py-2 text-[12.5px] font-bold text-[#475569] hover:bg-slate-50 hover:text-slate-900 rounded-lg transition-colors">
                    가격 차트 (Chart)
                  </a>
                  <a href="#a-indicators" className="block px-2.5 py-2 text-[12.5px] font-bold text-[#475569] hover:bg-slate-50 hover:text-slate-900 rounded-lg transition-colors">
                    지표별 신호 (Indicators)
                  </a>
                  <a href="#a-method" className="block px-2.5 py-2 text-[12.5px] font-bold text-[#475569] hover:bg-slate-50 hover:text-slate-900 rounded-lg transition-colors">
                    분석 방법 (Method)
                  </a>
                </nav>
              </div>

              <TechnicalTimeline trace={trace} />
            </aside>
          </div>
        </div>

        {/* Followups block */}
        <div className="mt-6">
          <TechnicalFollowups followups={followups} />
        </div>
      </article>
    </div>
  );
}
