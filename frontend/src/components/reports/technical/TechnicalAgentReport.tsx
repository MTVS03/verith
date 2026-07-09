"use client";

import { AlertTriangle, BarChart3, FileText, ShieldCheck } from "lucide-react";
import { SignalsSection } from "./SignalsSection";
import { StatusBadge } from "@/components/common/StatusBadge";
import {
  ALIGNMENT_LABELS,
  CONFIDENCE_LEVEL_LABELS,
  CONSENSUS_LABELS,
  DATA_STATUS_LABELS,
  REGIME_LABELS,
  RISK_FLAG_LABELS,
  TREND_LABELS,
  labelOf,
} from "@/constants/labels";
import type { TechnicalAgentOutput } from "@/types/technical-agent-output";
import type { ReactNode } from "react";

/**
 * 슈퍼바이저 technical 리포트(TechnicalAgentOutput) 렌더 — 에이전트가 준 값을 라벨 변환만.
 * confidence_level 은 에이전트가 제공(프론트 재계산 없음).
 */
function Section({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-card space-y-4">
      <div className="flex items-center gap-2 border-b border-slate-100 pb-3">
        <span className="text-indigo-600">{icon}</span>
        <h2 className="text-sm font-bold text-slate-800">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function InfoChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-3 bg-slate-50 border border-slate-200/60 rounded-xl">
      <span className="text-[10px] font-semibold text-slate-400">{label}</span>
      <div className="text-[12px] font-bold text-slate-700 mt-1">{value}</div>
    </div>
  );
}

export function TechnicalAgentReport({ output }: { output: TechnicalAgentOutput }) {
  const { regime, signal, interpretation, verification } = output;
  const gatePass = verification.outcome === "passed";
  const confLevel = signal?.confidence_level
    ? labelOf(CONFIDENCE_LEVEL_LABELS, signal.confidence_level)
    : null;

  return (
    <div className="space-y-6">
      {/* 상단: 국면/신호/신뢰도 요약 */}
      <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-card space-y-4">
        {interpretation.one_line_summary && (
          <p className="text-[15px] font-semibold text-slate-800">
            {interpretation.one_line_summary}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <StatusBadge tone="neutral" label={`국면 · ${labelOf(REGIME_LABELS, regime.final_regime)}`} />
          {signal?.consensus && (
            <StatusBadge tone="neutral" label={`신호 · ${labelOf(CONSENSUS_LABELS, signal.consensus)}`} />
          )}
          {confLevel && <StatusBadge tone="verified" label={`신뢰도 · ${confLevel}`} />}
          <StatusBadge
            tone={output.data_status === "normal" ? "neutral" : "warning"}
            label={labelOf(DATA_STATUS_LABELS, output.data_status)}
          />
          <StatusBadge
            tone={gatePass ? "verified" : "warning"}
            icon={<ShieldCheck className="w-3 h-3" />}
            label={gatePass ? "검증 PASS" : "검증 확인 필요"}
          />
        </div>
        {signal?.confidence_basis && (
          <p className="text-xs text-slate-500 bg-slate-50 border border-slate-200/60 rounded-lg p-3">
            <span className="font-bold text-slate-600">신뢰도 근거 </span>
            {signal.confidence_basis}
          </p>
        )}
      </div>

      {/* 핵심 요약 */}
      <Section icon={<FileText className="w-5 h-5" />} title="핵심 요약">
        {interpretation.text && (
          <p className="text-slate-600 text-[14px] leading-relaxed font-medium">
            {interpretation.text}
          </p>
        )}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <InfoChip label="최종 국면" value={labelOf(REGIME_LABELS, regime.final_regime)} />
          <InfoChip
            label="종합 신호"
            value={signal ? labelOf(CONSENSUS_LABELS, signal.consensus) : "—"}
          />
          <InfoChip
            label="주간 / 월간 추세"
            value={`${labelOf(TREND_LABELS, regime.weekly_trend)} / ${labelOf(TREND_LABELS, regime.monthly_trend)}`}
          />
          <InfoChip label="멀티프레임 정합" value={labelOf(ALIGNMENT_LABELS, regime.alignment_flag)} />
        </div>
        {interpretation.key_drivers.length > 0 && (
          <div>
            <div className="text-[11px] font-bold text-slate-400 mb-1.5">핵심 근거</div>
            <ul className="space-y-1">
              {interpretation.key_drivers.map((d, i) => (
                <li key={i} className="text-[12.5px] text-slate-600 flex gap-2">
                  <span className="text-indigo-400 mt-0.5">·</span>
                  <span>{d}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      {/* 지표별 기술 신호 */}
      <Section icon={<BarChart3 className="w-5 h-5" />} title="지표별 기술 신호">
        <SignalsSection items={output.technical_signals} />
      </Section>

      {/* 리스크 */}
      <Section icon={<AlertTriangle className="w-5 h-5" />} title="리스크 관찰점">
        {interpretation.risk_interpretation && (
          <p className="text-[12.5px] text-slate-600 leading-relaxed">
            {interpretation.risk_interpretation}
          </p>
        )}
        {output.risk && output.risk.items.length > 0 ? (
          <div className="space-y-2">
            {output.risk.items.map((r, i) => (
              <div
                key={i}
                className="p-3.5 bg-slate-50 border border-slate-200/60 rounded-xl flex gap-2.5 items-start"
              >
                <span className="px-2 py-0.5 rounded text-[9.5px] font-extrabold bg-amber-50 text-amber-600 shrink-0 mt-0.5">
                  {labelOf(RISK_FLAG_LABELS, r.flag)}
                </span>
                {r.note && <p className="text-[11.5px] text-slate-500 leading-snug">{r.note}</p>}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-400">확인된 주요 리스크 플래그가 없습니다.</p>
        )}
      </Section>
    </div>
  );
}
