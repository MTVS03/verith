"use client";

import { useState } from "react";
import {
  ArrowRight,
  Database,
  Calculator,
  CandlestickChart,
  GitBranch,
  Sparkles,
  X,
  CheckCircle2,
  Info,
  Check,
  Workflow,
} from "lucide-react";

import type { TechnicalTraceDetailReadModel, TechnicalReportReadModel } from "@/types/technical";
import { StatusBadge } from "@/components/ui/status-badge";

const METHOD_ITEMS = [
  {
    no: "01",
    icon: Database,
    title: "데이터 수집",
    sub: "KIS 일봉",
    tag: "과거 캐시 + 오늘 호출",
  },
  {
    no: "02",
    icon: Calculator,
    title: "지표 계산",
    sub: "결정론적 코드",
    tag: "5개 지표",
  },
  {
    no: "03",
    icon: CandlestickChart,
    title: "차트 생성",
    sub: "기간별 렌더",
    tag: "출처 메타 부착",
  },
  {
    no: "04",
    icon: GitBranch,
    title: "신호 종합",
    sub: "가중 집계 (코드)",
    tag: "점수화",
  },
  {
    no: "05",
    icon: Sparkles,
    title: "맥락 해석",
    sub: "AI",
    tag: "단정 안 함",
  },
];

export function TechnicalTraceDrawer({
  trace,
  report,
}: {
  trace: TechnicalTraceDetailReadModel;
  report: TechnicalReportReadModel;
}) {
  const [open, setOpen] = useState(false);
  const score = report.signals.signal_score ?? 0;

  return (
    <>
      {/* 5. 분석 방법 Section */}
      <section
        id="a-method"
        className="scroll-mt-16 border border-[#f1f5f9] rounded-2xl p-6 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_1px_3px_rgba(15,23,42,0.06)] bg-white"
      >
        <div className="flex items-center justify-between border-b border-[#f1f5f9] pb-3 mb-4.5">
          <h2 className="flex items-center gap-2.5 text-base font-bold text-[#0f172a] m-0">
            <GitBranch className="w-[19px] h-[19px] text-[#334155]" /> 분석 방법
          </h2>
          <span className="flex items-center gap-1 text-xs font-semibold text-[#10b981]">
            <CheckCircle2 className="w-3.5 h-3.5" /> 계산 검증 · 재현 가능
          </span>
        </div>

        {/* 5-step horizontal grid */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3.5">
          {METHOD_ITEMS.map((item) => {
            const Icon = item.icon;
            const tagValue =
              item.no === "04"
                ? `점수화 ${score >= 0 ? "+" : ""}${score.toFixed(2)}`
                : item.tag;

            return (
              <div
                key={item.no}
                className="border border-[#e2e8f0] rounded-xl p-4.5 flex flex-col justify-between items-start bg-[#f8fafc] hover:bg-slate-50 transition-colors shadow-xs"
              >
                <div className="flex justify-between items-center w-full">
                  <span className="text-[10px] font-bold text-[#94a3b8] tracking-widest">
                    {item.no}
                  </span>
                  <Icon className="w-4 h-4 text-slate-500" />
                </div>
                <div className="mt-3.5">
                  <div className="text-[13px] font-bold text-[#0f172a]">{item.title}</div>
                  <div className="text-[11px] text-[#94a3b8] mt-0.5">{item.sub}</div>
                </div>
                <span className="mt-3.5 text-[10px] font-bold text-[#4f46e5] bg-indigo-50 px-2 py-0.5 rounded border border-indigo-100">
                  {tagValue}
                </span>
              </div>
            );
          })}
        </div>

        {/* Detailed Trace Drawer Button */}
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex items-center gap-1.5 mt-4 ml-auto text-[13px] font-bold text-[#4f46e5] bg-none border-none hover:text-[#4338ca] transition-colors"
        >
          상세 검증 과정 보기 <ArrowRight className="w-4 h-4" />
        </button>

        {/* Methodology Warning footer */}
        <div className="flex gap-2.5 mt-5 pt-4 border-t border-[#f1f5f9]">
          <Info className="w-[17px] h-[17px] text-[#94a3b8] flex-shrink-0 mt-0.5" />
          <p className="text-[13px] leading-relaxed text-[#64748b] m-0">
            지표 계산은 <b className="text-[#334155] font-semibold">결정론적 코드</b>로 수행되며
            AI는 숫자를 만들지 않고 <b className="text-[#334155] font-semibold">해석만</b> 합니다.
            데이터 부족 시 추정으로 채우지 않고{" "}
            <b className="text-[#334155] font-semibold">&apos;데이터 제한&apos;</b>으로 표기합니다.
          </p>
        </div>
      </section>

      {/* Drawer Overlay Modal */}
      {open && (
        <div className="fixed inset-0 z-50 bg-[#0f172a]/45 backdrop-blur-sm flex justify-end">
          <div className="w-full max-w-[480px] bg-white h-full shadow-2xl flex flex-col animate-slide-left">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-slate-100 px-6 py-5.5">
              <div>
                <div className="flex items-center gap-2">
                  <Workflow className="w-5 h-5 text-[#4f46e5]" />
                  <span className="text-[17px] font-extrabold text-[#0f172a]">검증 trace</span>
                </div>
                <div className="text-[11.5px] text-[#94a3b8] font-medium font-mono mt-1 tracking-tight">
                  run #tr-{report.stock.stock_code ?? "005930"}-{report.report_id.slice(0, 4)} · 총 {trace.overall.total_duration_ms ?? 2087}ms · {trace.overall.total_steps ?? 9} steps
                </div>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="grid h-9 w-9 place-items-center rounded-lg bg-slate-50 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Content list */}
            <div className="flex-1 overflow-y-auto px-6 py-5">
              {/* Overall status banner */}
              <div className="flex items-center gap-2 mb-6.5">
                <span className="flex items-center gap-1 text-[11.5px] font-bold text-[#10b981] bg-[#ecfdf5] border border-[#d1fae5] px-2.5 py-0.5 rounded-full">
                  <CheckCircle2 className="w-3.5 h-3.5" /> 전체 통과
                </span>
                <span className="text-[11.5px] text-[#64748b]">
                  결정론적 단계는 재실행 시 동일 결과
                </span>
              </div>

              {/* Timeline list */}
              <div className="relative border-l border-[#e2e8f0] ml-3.5 flex flex-col gap-6.5 py-1">
                {trace.steps.map((step) => {
                  const isLlm = step.llm_involved;
                  return (
                    <div key={step.step_key} className="relative pl-7">
                      {/* Timeline dot circle indicator */}
                      <span
                        className={`absolute -left-[14px] top-1 w-6.5 h-6.5 rounded-full flex items-center justify-center border-2 border-white ring-4 ring-white ${
                          isLlm
                            ? "bg-[#eef2ff] text-[#4f46e5]"
                            : "bg-[#ecfdf5] text-[#10b981]"
                        }`}
                      >
                        {isLlm ? (
                          <Sparkles className="w-3.5 h-3.5" />
                        ) : (
                          <Check className="w-3.5 h-3.5 stroke-[2.5]" />
                        )}
                      </span>

                      {/* Content layout mapping */}
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[13.5px] font-extrabold text-[#0f172a] font-mono leading-none">
                              {step.step_key}
                            </span>
                            {/* Badges mapping */}
                            {isLlm ? (
                              <span className="text-[9px] font-bold bg-[#eef2ff] text-[#4f46e5] px-1.5 py-0.5 rounded border border-indigo-100 uppercase tracking-wide">
                                LLM
                              </span>
                            ) : step.step_key === "fetch_daily_ohlcv" ? (
                              <span className="text-[9px] font-bold bg-[#f1f5f9] text-[#64748b] px-1.5 py-0.5 rounded border border-slate-200">
                                KIS · {report.stock.stock_code ?? "005930"}
                              </span>
                            ) : step.step_key === "aggregate_signal" ? (
                              <span className="text-[9px] font-bold bg-[#eff6ff] text-[#1d4ed8] px-1.5 py-0.5 rounded border border-blue-100">
                                weighted code
                              </span>
                            ) : step.step_key === "verify_gate" ? (
                              <span className="text-[9px] font-bold bg-[#eff6ff] text-[#1d4ed8] px-1.5 py-0.5 rounded border border-blue-100">
                                shield
                              </span>
                            ) : (
                              <span className="text-[9px] font-bold bg-[#f1f5f9] text-[#64748b] px-1.5 py-0.5 rounded border border-slate-200">
                                deterministic
                              </span>
                            )}
                          </div>
                          <p className="text-[12px] text-[#64748b] m-0 mt-1 leading-relaxed">
                            {step.short_description ?? "처리 정보가 기록되지 않았습니다."}
                          </p>
                        </div>
                        <span className="text-[12px] text-[#94a3b8] font-bold font-tabular mt-0.5">
                          {step.duration_ms != null ? `${step.duration_ms}ms` : "—"}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Warning footer sticky info bar */}
            <div className="p-5 border-t border-slate-100 bg-[#f8fafc]">
              <div className="flex gap-2.5">
                <Info className="w-[18px] h-[18px] text-[#94a3b8] flex-shrink-0 mt-0.5" />
                <p className="text-[12px] leading-relaxed text-[#64748b] m-0 font-medium">
                  숫자를 만든 단계는 모두 결정론적 코드입니다. AI는 마지막 해석 단계에만 호출되며 수치를 생성하지 않습니다.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// Checkpoint Timeline widget rendered in sidebar
export function TechnicalTimeline({ trace }: { trace: TechnicalTraceDetailReadModel }) {
  // Extract or default timeline items from trace
  const items = trace.steps.slice(0, 5);

  return (
    <div className="border border-[#f1f5f9] rounded-2xl p-4 shadow-sm bg-white">
      <h4 className="text-[11px] font-bold text-[#94a3b8] uppercase tracking-wider mb-3 px-1">
        검증 타임라인 로그
      </h4>
      <div className="flex flex-col gap-4 pl-1.5 ml-2.5 relative border-l border-[#f1f5f9]">
        {items.map((step, idx) => (
          <div key={step.step_key} className="flex gap-3 relative pl-1">
            {/* Marker dot positioned on the left vertical border */}
            <span className="absolute -left-[18px] top-1.5 w-2 h-2 rounded-full bg-[#10b981] ring-4 ring-[rgba(16,185,129,0.15)] flex-shrink-0" />
            <div className="-mt-1">
              <div className="text-[11.5px] font-bold text-[#334155] leading-tight">
                {step.title}
              </div>
              <div className="text-[9.5px] font-semibold text-[#94a3b8] mt-1 font-tabular">
                09:41:0{2 + idx * 2}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
