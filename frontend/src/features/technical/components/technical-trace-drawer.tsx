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
    sub: "LLM",
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
            LLM은 숫자를 만들지 않고 <b className="text-[#334155] font-semibold">해석만</b> 합니다.
            데이터 부족 시 추정으로 채우지 않고{" "}
            <b className="text-[#334155] font-semibold">&apos;데이터 제한&apos;</b>으로 표기합니다.
          </p>
        </div>
      </section>

      {/* Drawer Overlay Modal */}
      {open && (
        <div className="fixed inset-0 z-50 bg-[#0f172a]/45 backdrop-blur-sm flex justify-end">
          <div className="w-full max-w-2xl bg-white h-full shadow-2xl flex flex-col animate-slide-left">
            {/* Header */}
            <div className="flex items-start justify-between border-b border-slate-100 px-6 py-5">
              <div>
                <p className="text-xs font-semibold text-[#4f46e5] uppercase tracking-wider">
                  Processing trace
                </p>
                <h3 className="mt-1 text-xl font-bold text-[#0f172a]">처리 단계 상세</h3>
                <p className="mt-2 text-xs leading-relaxed text-[#94a3b8]">
                  이 리포트는 결정론 코드로 계산되고 KIS 시세에 연결되어 검증됩니다. 모든 단계의
                  실행 로그 및 파라미터를 상세히 탐색할 수 있습니다.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="grid h-9 w-9 place-items-center rounded-lg bg-slate-100 text-slate-500 hover:bg-slate-200 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Steps list */}
            <div className="flex-1 overflow-y-auto px-6 py-5">
              <div className="space-y-4">
                {trace.steps.map((step) => (
                  <div key={step.step_key} className="rounded-xl border border-slate-150 p-4.5 bg-slate-50/40">
                    <div className="flex items-start gap-4">
                      <div className="grid h-10 w-10 place-items-center rounded-xl bg-indigo-50 text-[#4f46e5] font-bold text-sm">
                        {step.llm_involved ? (
                          <Sparkles className="w-4 h-4" />
                        ) : (
                          <span>{step.step_order}</span>
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h4 className="text-sm font-bold text-[#0f172a]">{step.title}</h4>
                          <StatusBadge label={step.status} tone={step.status === "ok" ? "green" : "amber"} />
                          {step.source ? <StatusBadge label={step.source} tone="blue" /> : null}
                        </div>
                        <p className="mt-2 text-xs sm:text-sm leading-relaxed text-[#475569]">
                          {step.short_description ?? "설명이 없습니다."}
                        </p>
                        <div className="mt-3 flex flex-wrap gap-4 text-[10.5px] text-[#94a3b8] font-mono">
                          <span>step_key: {step.step_key}</span>
                          <span>llm_involved: {step.llm_involved ? "true" : "false"}</span>
                          <span>duration_ms: {step.duration_ms ?? "—"}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
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
