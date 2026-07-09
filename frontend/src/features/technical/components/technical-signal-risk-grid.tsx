"use client";

import { Calculator, GitBranch, ShieldAlert } from "lucide-react";
import type { TechnicalReportReadModel } from "@/types/technical";
import { formatNumber } from "@/lib/format";
import { signalLabel } from "@/lib/technical-labels";
import { IndicatorCardComponent } from "./indicator-card";

const INDICATOR_MAP: Record<string, { name: string; weight: string; icon: string }> = {
  moving_average: { name: "이동평균", weight: "30%", icon: "trending-up" },
  rsi: { name: "RSI", weight: "20%", icon: "gauge" },
  volume: { name: "거래량", weight: "20%", icon: "bar-chart-3" },
  support_resistance: { name: "지지저항", weight: "20%", icon: "ruler" },
  pattern: { name: "패턴", weight: "10%", icon: "candlestick-chart" },
};

export function TechnicalSignalRiskGrid({ report }: { report: TechnicalReportReadModel }) {
  const signalItems = report.signals.items;
  const risks = report.risks.items;

  // Build the complete list of 5 indicators to guarantee standardized layout (fallback only)
  const allIndicators = ["moving_average", "rsi", "volume", "support_resistance", "pattern"];

  const getSignalBadgeStyle = (sig: string | null) => {
    if (sig === "positive") {
      return "text-[#10b981] bg-[rgba(16,185,129,0.10)]";
    }
    if (sig === "negative") {
      return "text-[#f43f5e] bg-[rgba(244,63,94,0.10)]";
    }
    return "text-[#64748b] bg-slate-100";
  };

  return (
    <div className="flex flex-col gap-6">
      {/* 1. 지표별 신호 Section */}
      <section
        id="a-indicators"
        className="scroll-mt-16 border border-[#f1f5f9] rounded-2xl p-6 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_1px_3px_rgba(15,23,42,0.06)] bg-white"
      >
        <div className="flex items-center justify-between border-b border-[#f1f5f9] pb-3 mb-4.5">
          <h2 className="flex items-center gap-2.5 text-base font-bold text-[#0f172a] m-0">
            <GitBranch className="w-[19px] h-[19px] text-[#334155]" /> 지표별 신호
          </h2>
          <span className="flex items-center gap-1 text-xs font-semibold text-[#059669] bg-[rgba(16,185,129,0.1)] px-2.5 py-1 rounded-full">
            <Calculator className="w-3.5 h-3.5" /> 코드 계산 · 결정론
          </span>
        </div>

        <p className="flex items-start gap-1.5 text-[13.5px] leading-relaxed text-[#475569] m-0 mb-2">
          <GitBranch className="w-4 h-4 text-[#94a3b8] flex-shrink-0 mt-0.5" />
          <span>
            <b className="font-semibold text-[#059669]">판정·수치·가중치는 코드가 계산</b>하고,{" "}
            <b className="font-semibold text-[#4f46e5]">설명 문장은 LLM이 그 값을 해석</b>합니다.
            LLM은 판정을 바꿀 수 없으며, 검증을 통과한 문장만 표시됩니다.
          </span>
        </p>
        <p className="text-[13.5px] text-[#64748b] m-0 mb-5 flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-slate-300" />
          신호는 단정하지 않고 5개 지표의 종합(가중 집계 · 종합{" "}
          <b className="text-[#334155] font-semibold font-tabular">
            {report.signals.signal_score && report.signals.signal_score >= 0 ? "+" : ""}
            {report.signals.signal_score?.toFixed(2) ?? "0.00"}
          </b>
          )으로 제시합니다. 상충되면 <b className="text-[#334155] font-semibold">중립</b>으로 표기합니다.
        </p>

        {/* Strategies Cards list */}
        <div className="flex flex-col gap-5">
          {report.indicator_cards && report.indicator_cards.length > 0 ? (
            report.indicator_cards.map((card, idx) => (
              <IndicatorCardComponent key={card.indicator} card={card} index={idx} />
            ))
          ) : (
            allIndicators.map((indKey, idx) => {
              const staticMeta = INDICATOR_MAP[indKey] || { name: indKey, weight: "10%", icon: "info" };
              const item = signalItems.find((i) => i.indicator === indKey) || {
                indicator: indKey,
                signal: "neutral",
                value: null,
                metrics: [],
                detail: "이 지표는 계산 범위가 충분하지 않거나 제공되지 않았습니다.",
                detail_source: "template_fallback",
              };

              return (
                <div
                  key={indKey}
                  className="border border-[#e2e8f0] rounded-xl p-5 flex gap-5 items-start bg-white shadow-[0_1px_2px_rgba(15,23,42,0.03)] hover:shadow-md transition-shadow"
                >
                  {/* Left side card labels */}
                  <div className="flex flex-col items-center gap-1.5 w-[76px] flex-shrink-0">
                    <span className="text-[10px] font-bold text-[#94a3b8] tracking-widest uppercase">
                      STRATEGY {String(idx + 1).padStart(2, "0")}
                    </span>
                    <span className="text-base font-extrabold text-[#0f172a] whitespace-nowrap">
                      {staticMeta.name}
                    </span>
                    <span
                      className={`text-[11px] font-bold px-2 py-0.5 rounded-md ${getSignalBadgeStyle(
                        item.signal
                      )}`}
                    >
                      {signalLabel(item.signal)}
                    </span>
                    <span className="text-[10px] font-semibold text-[#94a3b8]">
                      가중치 {staticMeta.weight}
                    </span>
                  </div>

                  {/* Right side detailed content */}
                  <div className="flex-1 min-w-0 flex flex-col gap-3">
                    <p className="text-[13.5px] leading-relaxed text-[#334155] m-0">
                      {item.detail ?? "설명이 없습니다."}
                    </p>
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {item.value !== null && (
                        <span className="text-[11px] font-bold px-2.5 py-1 bg-[#f8fafc] border border-[#e2e8f0] rounded-lg text-[#475569] font-tabular">
                          값: {formatNumber(item.value)}
                        </span>
                      )}
                      {item.metrics.map((metric) => (
                        <span
                          key={metric}
                          className="text-[11px] font-semibold px-2.5 py-1 bg-[#f8fafc] border border-[#e2e8f0] rounded-lg text-[#475569]"
                        >
                          {metric}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>

      {/* 2. 리스크 / 경고 Section (Clean layout insertion to prevent loss of backend warnings) */}
      {risks.length > 0 && (
        <section className="border border-rose-100 rounded-2xl p-5 bg-rose-50/20 shadow-xs">
          <h3 className="flex items-center gap-2 text-sm font-bold text-rose-800 mb-3 m-0">
            <ShieldAlert className="w-4.5 h-4.5 text-rose-700" /> 리스크 / 경고 모니터링
          </h3>
          <div className="flex flex-col gap-3">
            {risks.map((risk) => (
              <div
                key={risk.flag}
                className="rounded-xl border border-rose-100 bg-white p-4 shadow-sm"
              >
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <p className="text-sm font-bold text-rose-800 m-0">
                    {risk.flag === "volume_not_confirmed" ? "거래량 확인 부족" : risk.flag}
                  </p>
                  {risk.ref_price !== null && (
                    <span className="text-xs font-bold text-rose-500 font-tabular">
                      기준가: ₩{formatNumber(risk.ref_price)}
                    </span>
                  )}
                </div>
                <p className="mt-2 text-xs sm:text-sm leading-relaxed text-[#475569] m-0">
                  {risk.note ?? "설명이 없습니다."}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
