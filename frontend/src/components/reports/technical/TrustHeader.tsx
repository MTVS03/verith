"use client";

import { GitFork, Link2, ShieldAlert, ShieldCheck } from "lucide-react";
import { AGENT_TYPE_LABELS, DATA_STATUS_LABELS, labelOf } from "@/constants/labels";
import { confidencePercent, confidenceLevelLabel, formatDate } from "@/utils/format";
import type { TechnicalReportReadModel } from "@/types/technical-report";

/**
 * 리포트 상단 헤더 — 종목 컨텍스트 + 신뢰 지표 4종(trust_summary projection).
 * 모든 값은 백엔드 집계값을 표시 변환만 한다(프론트 재계산 없음).
 */
export function TrustHeader({ report }: { report: TechnicalReportReadModel }) {
  const { stock, summary, meta, trust_summary } = report;
  const sq = trust_summary.signal_quality;
  const gate = trust_summary.verification_gate;
  const coverage = Math.round(trust_summary.source_linkage.source_coverage_ratio * 100);
  const confPct = confidencePercent(sq.confidence);
  const confLabel = confidenceLevelLabel(sq.confidence);
  const gatePass = gate.outcome === "passed" && !gate.verification_warning;

  return (
    <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-card space-y-5">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span className="px-2.5 py-0.5 bg-indigo-50 text-indigo-700 text-[10px] font-bold rounded-full">
            {labelOf(AGENT_TYPE_LABELS, "technical")}
          </span>
          <span className="text-[11px] text-slate-400 font-semibold num">
            {formatDate(meta.as_of)}
          </span>
        </div>
        <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 leading-snug">
          {(stock.stock_name ?? stock.stock_code)} 기술 리포트
        </h1>
        <div className="flex items-center gap-2.5 pt-1 flex-wrap">
          <span className="w-7 h-7 rounded-lg bg-slate-100 text-slate-500 font-extrabold flex items-center justify-center text-[10.5px]">
            {(stock.stock_name ?? stock.stock_code).slice(0, 2)}
          </span>
          <span className="text-xs font-bold text-slate-800">
            {stock.stock_name ?? stock.stock_code}
          </span>
          <span className="text-xs text-slate-400 num">{stock.stock_code}</span>
          {stock.market && (
            <>
              <span className="text-slate-300">·</span>
              <span className="text-xs text-slate-500">{stock.market}</span>
            </>
          )}
        </div>
        {summary.one_line_summary && (
          <p className="text-sm text-slate-600 font-medium pt-1 leading-relaxed">
            {summary.one_line_summary}
          </p>
        )}
      </div>

      {/* 신뢰 지표 4종 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-5 border-t border-slate-100">
        <div className="space-y-1">
          <div className="text-[11px] font-semibold text-slate-400">AI 신뢰도</div>
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-black text-emerald-600 num">
              {confPct ?? "—"}
            </span>
            {confPct != null && <span className="text-xs font-bold text-emerald-500">%</span>}
            {confLabel && (
              <span className="text-xs font-bold text-slate-500 ml-1">{confLabel}</span>
            )}
          </div>
          <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden mt-1.5">
            <div
              className="h-full bg-emerald-500 rounded-full"
              style={{ width: `${confPct ?? 0}%` }}
            />
          </div>
        </div>

        <div className="space-y-1">
          <div className="text-[11px] font-semibold text-slate-400">검증된 지표 노드</div>
          <div className="flex items-center gap-1 text-slate-800">
            <GitFork className="w-5 h-5 text-indigo-500" />
            <span className="text-xl font-extrabold num">
              {trust_summary.source_linkage.total_signal_items}건
            </span>
          </div>
        </div>

        <div className="space-y-1">
          <div className="text-[11px] font-semibold text-slate-400">출처 연결률</div>
          <div className="flex items-center gap-1 text-slate-800">
            <Link2 className="w-5 h-5 text-indigo-500" />
            <span className="text-xl font-extrabold num">{coverage}%</span>
          </div>
        </div>

        <div className="space-y-1">
          <div className="text-[11px] font-semibold text-slate-400">검증 게이트</div>
          <div
            className={`flex items-center gap-1.5 font-extrabold text-sm pt-0.5 ${
              gatePass ? "text-emerald-600" : "text-amber-600"
            }`}
          >
            <span
              className={`w-6 h-6 rounded-full grid place-items-center ${
                gatePass
                  ? "bg-emerald-100 text-emerald-600"
                  : "bg-amber-100 text-amber-600"
              }`}
            >
              <ShieldCheck className="w-4 h-4" />
            </span>
            <span>{gatePass ? "PASS" : "확인 필요"}</span>
          </div>
          <div className="text-[10px] text-slate-400 mt-0.5">
            데이터 {labelOf(DATA_STATUS_LABELS, meta.data_status)}
          </div>
        </div>
      </div>

      <div className="p-3.5 bg-emerald-50/50 border border-emerald-100/80 rounded-xl flex gap-2.5 items-center">
        <span className="text-emerald-600 shrink-0">
          <ShieldAlert className="w-4 h-4" />
        </span>
        <p className="text-xs text-emerald-800 leading-snug font-medium">
          이 리포트의 지표 값과 해석은 저장된 계산 결과의 검증을 거친 것입니다. 검증 게이트를 통과하지
          못한 수치는 리포트에 반영되지 않습니다.
        </p>
      </div>
    </div>
  );
}
