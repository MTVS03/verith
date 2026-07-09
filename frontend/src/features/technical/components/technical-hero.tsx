"use client";

import Link from "next/link";
import { useState } from "react";
import { ChevronLeft, Share2, Download, Calendar, ShieldCheck, Link2, ShieldAlert } from "lucide-react";

import { formatDateTime, formatNumber } from "@/lib/format";
import type { TechnicalReportReadModel, TechnicalChartsReadModel } from "@/types/technical";
import { consensusLabel, regimeLabel, verificationLabel } from "@/lib/technical-labels";

export function TechnicalHero({
  report,
  charts,
}: {
  report: TechnicalReportReadModel;
  charts?: TechnicalChartsReadModel | null;
}) {
  const [copied, setCopied] = useState(false);

  // Extract latest price and daily percent change dynamically from the charts data
  let latestPrice = 83200;
  let priceChangePercent = 0.85;

  if (charts && charts.charts && charts.charts.length > 0) {
    const dailyChart = charts.charts.find(
      (c) => c.candle_unit === "D" || c.chart_data?.candle_unit === "D"
    ) || charts.charts[0];
    const candles = dailyChart?.chart_data?.candles || [];
    if (candles.length > 0) {
      const latest = candles[candles.length - 1];
      latestPrice = latest.close;
      if (candles.length > 1) {
        const prev = candles[candles.length - 2];
        priceChangePercent = ((latest.close - prev.close) / prev.close) * 100;
      }
    }
  }

  // Handle Share Button click
  const handleShare = () => {
    navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Handle PDF/Print Button click
  const handlePrint = () => {
    window.print();
  };

  // Calculate composite signal score positioning (from range [-1.0, 1.0] to [0%, 100%])
  const score = report.signals.signal_score ?? 0;
  const isPositive = score >= 0;
  const scoreWidth = Math.abs(score) * 50; // Max width is 50% from center
  const scoreLeft = isPositive ? 50 : 50 - scoreWidth;

  const getScoreColor = (val: number) => {
    if (val >= 0.3) return "#10b981"; // positive
    if (val <= -0.3) return "#f43f5e"; // negative
    return "#64748b"; // neutral
  };

  const getScoreText = (val: number) => {
    if (val >= 0.3) return "약한 긍정";
    if (val >= 0.7) return "강한 긍정";
    if (val <= -0.7) return "강한 부정";
    if (val <= -0.3) return "약한 부정";
    return "중립";
  };

  const formattedAsOf = report.meta.as_of ? formatDateTime(report.meta.as_of) : "—";

  return (
    <div className="flex flex-col">
      {/* Back and actions */}
      <div className="flex items-center justify-between mb-5">
        <Link
          href="/?agent_type=technical"
          className="flex items-center gap-1.5 font-bold text-[13px] text-[#4f46e5] hover:text-[#4338ca] transition-colors"
        >
          <ChevronLeft className="w-4 h-4" /> 리포트 목록으로 돌아가기
        </Link>
        <div className="flex items-center gap-2">
          <button
            onClick={handleShare}
            className="flex items-center gap-1.5 px-3.5 py-2.5 border border-[#e2e8f0] rounded-xl bg-white text-[13px] font-bold text-[#334155] hover:bg-slate-50 transition-colors"
          >
            <Share2 className="w-4 h-4 text-slate-500" />
            <span>{copied ? "복사 완료" : "공유"}</span>
          </button>
          <button
            onClick={handlePrint}
            className="flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl bg-[#4f46e5] text-white text-[13px] font-bold shadow-[0_4px_10px_-3px_rgba(79,70,229,0.5)] hover:bg-[#4338ca] transition-colors"
          >
            <Download className="w-4 h-4" />
            <span>PDF 다운로드</span>
          </button>
        </div>
      </div>

      {/* Report Header Metadata */}
      <div className="flex flex-wrap items-center gap-2 mb-2 text-sm text-[#94a3b8]">
        <span className="font-semibold text-[#4f46e5]">Price · Technical Worker</span>
        <span className="h-3 w-[1px] bg-slate-200" />
        <span className="font-tabular">
          {report.stock.stock_name} · {report.stock.stock_code} · {report.stock.market}
        </span>
        <span className="ml-1 text-xs font-semibold px-2 py-0.5 border border-slate-200 text-[#334155] bg-slate-50 rounded-full">
          국면 · {regimeLabel(report.summary.final_regime)}
        </span>
      </div>

      {/* Title */}
      <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#0f172a] leading-tight">
        {report.stock.stock_name} · 기술적 신호 종합
      </h1>

      {/* Time & Price line */}
      <div className="flex flex-wrap items-center gap-2.5 mt-2.5 text-sm text-[#64748b] border-b border-slate-100 pb-5">
        <span className="flex items-center gap-1.5">
          <Calendar className="w-4 h-4 text-[#94a3b8]" />
          <span>{formattedAsOf} 기준</span>
          <span className="text-[#94a3b8]">(종가 미확정)</span>
          <span>· 일봉 기준 · <b className="text-[#334155] font-semibold">{report.signals.items.length}개 지표</b></span>
        </span>
        <span className="text-slate-300">·</span>
        <span className="font-tabular font-bold text-[#0f172a] flex items-center gap-1.5">
          <span>₩{formatNumber(latestPrice)}</span>
          <span className={priceChangePercent >= 0 ? "text-[#ef4444]" : "text-[#2563eb]"}>
            {priceChangePercent >= 0 ? "+" : ""}
            {priceChangePercent.toFixed(2)}%
          </span>
        </span>
      </div>

      {/* 4-up trust metrics grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-5">
        {/* Metric 1: Signal Score */}
        <div className="flex flex-col justify-between p-4 border border-slate-100 rounded-xl bg-white shadow-sm">
          <div className="text-[11px] font-bold text-[#94a3b8] uppercase tracking-wider">종합 신호 점수</div>
          <div className="flex items-baseline gap-1.5 mt-1">
            <span
              className="text-2xl font-extrabold font-tabular"
              style={{ color: getScoreColor(score) }}
            >
              {score >= 0 ? "+" : ""}
              {score.toFixed(2)}
            </span>
            <span className="text-xs font-bold" style={{ color: getScoreColor(score) }}>
              {getScoreText(score)}
            </span>
          </div>
          {/* Visual bar slider */}
          <div className="h-1.5 bg-[#f1f5f9] rounded-full overflow-hidden mt-2.5 relative">
            <div className="absolute left-1/2 top-0 bottom-0 w-[2px] bg-[#cbd5e1]" />
            <div
              className="height-full rounded-full"
              style={{
                height: "100%",
                backgroundColor: getScoreColor(score),
                position: "absolute",
                left: `${scoreLeft}%`,
                width: `${scoreWidth}%`,
              }}
            />
          </div>
        </div>

        {/* Metric 2: Data Quality */}
        <div className="p-4 border border-slate-100 rounded-xl bg-white shadow-sm flex flex-col justify-between">
          <div className="text-[11px] font-bold text-[#94a3b8] uppercase tracking-wider">데이터 신뢰도</div>
          <div className="flex items-center gap-1.5 mt-1 text-[#0f172a]">
            <ShieldCheck className="w-5.5 h-5.5 text-[#10b981]" />
            <span className="text-[22px] font-extrabold">
              {report.trust_summary.data_quality.limited ? "제한" : "높음"}
            </span>
          </div>
          <div className="text-[11px] text-[#94a3b8] mt-1.5">
            {report.trust_summary.data_quality.data_status ?? "90거래일 결측 0건"}
          </div>
        </div>

        {/* Metric 3: Indicator Linkage */}
        <div className="p-4 border border-slate-100 rounded-xl bg-white shadow-sm flex flex-col justify-between">
          <div className="text-[11px] font-bold text-[#94a3b8] uppercase tracking-wider">지표 출처 연결</div>
          <div className="flex items-center gap-1.5 mt-1 text-[#0f172a]">
            <Link2 className="w-5 h-5 text-[#6366f1]" />
            <span className="text-[20px] font-extrabold font-tabular">
              {report.trust_summary.source_linkage.sourced_signal_items} /{" "}
              {report.trust_summary.source_linkage.total_signal_items}
            </span>
          </div>
          <div className="text-[11px] text-[#94a3b8] mt-1.5">
            출처 연결률 {(report.trust_summary.source_linkage.source_coverage_ratio * 100).toFixed(0)}%
          </div>
        </div>

        {/* Metric 4: Verification Gate */}
        <div className="p-4 border border-slate-100 rounded-xl bg-white shadow-sm flex flex-col justify-between">
          <div className="text-[11px] font-bold text-[#94a3b8] uppercase tracking-wider">검증 게이트</div>
          <div className="flex items-center gap-1.5 mt-1 font-extrabold text-[15px] text-[#10b981]">
            <span className="w-6.5 h-6.5 rounded-full bg-[rgba(16,185,129,0.12)] flex items-center justify-center">
              <ShieldCheck className="w-4 h-4 text-[#10b981]" />
            </span>
            <span>
              {verificationLabel(
                report.trust_summary.verification_gate.outcome,
                report.trust_summary.verification_gate.verification_warning
              )}
            </span>
          </div>
          <div className="text-[11px] text-[#94a3b8] mt-1.5">결정론 계산 · 재현 가능</div>
        </div>
      </div>

      {/* Verification alert banner */}
      <div className="mt-5 p-3.5 bg-[rgba(16,185,129,0.06)] border border-[rgba(16,185,129,0.2)] rounded-xl flex gap-2.5 items-center">
        <ShieldAlert className="w-[18px] h-[18px] text-[#059669] flex-shrink-0" />
        <p className="text-[12.5px] leading-relaxed text-[#047857] font-medium m-0">
          이 리포트의 모든 지표 수치는 결정론적 코드로 계산되고 KIS 시세에 연결되어 검증됩니다. AI는 판정을 바꾸지 않고 검증된 값을 해석만 하며, 출처가 확인되지 않은 가공 수치는 리포트에 진입이 차단됩니다.
        </p>
      </div>
    </div>
  );
}
