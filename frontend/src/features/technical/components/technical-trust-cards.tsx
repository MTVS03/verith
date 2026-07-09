import { BarChart3, Link2, ShieldCheck, Sparkles } from "lucide-react";

import { formatPercent, formatSignedScore } from "@/lib/format";
import type { TechnicalReportReadModel } from "@/types/technical";
import { SectionCard } from "@/components/ui/section-card";
import { consensusLabel, verificationLabel } from "@/lib/technical-labels";

export function TechnicalTrustCards({ report }: { report: TechnicalReportReadModel }) {
  const cards = [
    {
      icon: Sparkles,
      title: "데이터 신뢰도",
      value: formatSignedScore(report.trust_summary.signal_quality.signal_score),
      meta:
        report.trust_summary.signal_quality.signal_label ??
        consensusLabel(report.trust_summary.signal_quality.consensus) ??
        "—",
      caption:
        report.trust_summary.signal_quality.confidence_basis ??
        "저장된 technical signal projection",
      tone: "indigo" as const,
    },
    {
      icon: BarChart3,
      title: "데이터 품질",
      value: report.trust_summary.data_quality.limited ? "제한" : "정상",
      meta: `차트 ${report.trust_summary.data_quality.chart_count}개 · ${report.trust_summary.data_quality.available_periods.join(", ") || "—"}`,
      caption: report.trust_summary.data_quality.data_status ?? "unknown",
      tone: "blue" as const,
    },
    {
      icon: ShieldCheck,
      title: "검증 게이트",
      value: verificationLabel(
        report.trust_summary.verification_gate.outcome,
        report.trust_summary.verification_gate.verification_warning,
      ),
      meta: report.trust_summary.verification_gate.outcome ?? "—",
      caption: `calc ${booleanLabel(report.trust_summary.verification_gate.calc_passed)} · regime ${booleanLabel(report.trust_summary.verification_gate.regime_passed)} · label ${booleanLabel(report.trust_summary.verification_gate.label_matched)}`,
      tone: report.trust_summary.verification_gate.verification_warning
        ? ("amber" as const)
        : ("green" as const),
    },
    {
      icon: Link2,
      title: "지표 출처 연결",
      value: formatPercent(report.trust_summary.source_linkage.source_coverage_ratio),
      meta: `${report.trust_summary.source_linkage.sourced_signal_items} / ${report.trust_summary.source_linkage.total_signal_items}`,
      caption: "AI 분석 커버리지",
      tone: "emerald" as const,
    },
  ];

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <SectionCard key={card.title} title={card.title} className="p-5">
            <div className="space-y-4">
              <div
                className={
                  card.tone === "emerald"
                    ? "grid h-11 w-11 place-items-center rounded-2xl bg-emerald-50 text-emerald-600"
                    : card.tone === "green"
                      ? "grid h-11 w-11 place-items-center rounded-2xl bg-emerald-50 text-emerald-600"
                      : card.tone === "amber"
                        ? "grid h-11 w-11 place-items-center rounded-2xl bg-amber-50 text-amber-600"
                        : card.tone === "blue"
                          ? "grid h-11 w-11 place-items-center rounded-2xl bg-sky-50 text-sky-600"
                          : "grid h-11 w-11 place-items-center rounded-2xl bg-indigo-50 text-indigo-600"
                }
              >
                <Icon className="h-5 w-5" />
              </div>
              <div className="space-y-1">
                <p className="text-3xl font-bold tracking-tight text-slate-950">{card.value}</p>
                <p className="text-sm font-medium text-slate-700">{card.meta}</p>
                <p className="text-xs leading-6 text-slate-400">{card.caption}</p>
              </div>
            </div>
          </SectionCard>
        );
      })}
    </div>
  );
}

function booleanLabel(value: boolean | null): string {
  if (value == null) return "—";
  return value ? "Y" : "N";
}
