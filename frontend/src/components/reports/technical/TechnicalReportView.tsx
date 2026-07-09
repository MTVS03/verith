"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  BarChart3,
  ChevronLeft,
  FileText,
  GitFork,
  Share2,
  ShieldCheck,
} from "lucide-react";
import { useTechnicalReport } from "@/lib/hooks/useTechnicalReport";
import { useToast } from "@/components/common/Toast";
import { TrustHeader } from "./TrustHeader";
import { SignalsSection } from "./SignalsSection";
import {
  ALIGNMENT_LABELS,
  CONSENSUS_LABELS,
  DATA_STATUS_LABELS,
  PERIOD_LABELS,
  REGIME_LABELS,
  RISK_FLAG_LABELS,
  SOURCE_LABELS,
  TREND_LABELS,
  labelOf,
} from "@/constants/labels";
import type { TechnicalReportReadModel } from "@/types/technical-report";

/** 섹션 카드 래퍼 — 아이콘 + 제목 + 본문(mockup 섹션 헤더 패턴). */
function Section({
  id,
  icon,
  title,
  children,
}: {
  id: string;
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <section
      id={id}
      className="scroll-mt-6 bg-white rounded-2xl border border-slate-200/80 p-6 shadow-card space-y-4"
    >
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

function ReportBody({ report }: { report: TechnicalReportReadModel }) {
  const { summary, interpretation, drivers, signals, risks, charts, trust_summary } =
    report;
  const trace = report.trace_summary;

  return (
    <div className="space-y-6">
      {/* 핵심 요약 */}
      <Section id="sec-summary" icon={<FileText className="w-5 h-5" />} title="핵심 요약">
        {interpretation.text && (
          <p className="text-slate-600 text-[14px] leading-relaxed font-medium">
            {interpretation.text}
          </p>
        )}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-1">
          <InfoChip label="최종 국면" value={labelOf(REGIME_LABELS, summary.final_regime)} />
          <InfoChip label="종합 신호" value={labelOf(CONSENSUS_LABELS, signals.consensus)} />
          <InfoChip
            label="주간 / 월간 추세"
            value={`${labelOf(TREND_LABELS, summary.weekly_trend)} / ${labelOf(TREND_LABELS, summary.monthly_trend)}`}
          />
          <InfoChip
            label="멀티프레임 정합"
            value={labelOf(ALIGNMENT_LABELS, summary.alignment_flag)}
          />
        </div>

        {drivers.key_drivers.length > 0 && (
          <div className="pt-1">
            <div className="text-[11px] font-bold text-slate-400 mb-1.5">핵심 근거</div>
            <ul className="space-y-1">
              {drivers.key_drivers.map((d, i) => (
                <li key={i} className="text-[12.5px] text-slate-600 flex gap-2">
                  <span className="text-indigo-400 mt-0.5">·</span>
                  <span>{d}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {drivers.warning_points.length > 0 && (
          <div className="pt-1">
            <div className="text-[11px] font-bold text-slate-400 mb-1.5">주의 관찰점</div>
            <ul className="space-y-1">
              {drivers.warning_points.map((d, i) => (
                <li key={i} className="text-[12.5px] text-slate-600 flex gap-2">
                  <span className="text-amber-400 mt-0.5">·</span>
                  <span>{d}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      {/* 지표별 기술 신호 */}
      <Section
        id="sec-signals"
        icon={<BarChart3 className="w-5 h-5" />}
        title="지표별 기술 신호"
      >
        {signals.confidence_basis && (
          <p className="text-[11px] text-slate-500 bg-slate-50 border border-slate-200/60 rounded-lg p-2.5">
            {signals.confidence_basis}
          </p>
        )}
        <SignalsSection items={signals.items} />
      </Section>

      {/* 리스크 */}
      <Section
        id="sec-risk"
        icon={<AlertTriangle className="w-5 h-5" />}
        title="리스크 관찰점"
      >
        {interpretation.risk_interpretation && (
          <p className="text-[12.5px] text-slate-600 leading-relaxed">
            {interpretation.risk_interpretation}
          </p>
        )}
        {risks.items.length > 0 ? (
          <div className="space-y-2">
            {risks.items.map((r, i) => (
              <div
                key={i}
                className="p-3.5 bg-slate-50 border border-slate-200/60 rounded-xl flex gap-2.5 items-start"
              >
                <span className="px-2 py-0.5 rounded text-[9.5px] font-extrabold bg-amber-50 text-amber-600 shrink-0 mt-0.5">
                  {labelOf(RISK_FLAG_LABELS, r.flag)}
                </span>
                {r.note && (
                  <p className="text-[11.5px] text-slate-500 leading-snug">{r.note}</p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-400">확인된 주요 리스크 플래그가 없습니다.</p>
        )}
      </Section>

      {/* 차트 (Phase 4c 예정) */}
      <Section id="sec-charts" icon={<BarChart3 className="w-5 h-5" />} title="가격 차트">
        <p className="text-xs text-slate-500 leading-relaxed">
          제공 기간:{" "}
          {charts.available_periods.map((p) => labelOf(PERIOD_LABELS, p)).join(" · ")}
        </p>
        <div className="py-10 bg-slate-50/60 border border-dashed border-slate-200 rounded-xl text-center">
          <p className="text-[11px] font-semibold text-slate-400">
            차트 렌더는 다음 단계에서 연동됩니다.
          </p>
        </div>
      </Section>

      {/* 검증 / 생성 경로 */}
      <Section
        id="sec-verification"
        icon={<ShieldCheck className="w-5 h-5" />}
        title="검증 · 생성 경로"
      >
        <div className="grid grid-cols-3 gap-3">
          {[
            ["계산 검증", trust_summary.verification_gate.calc_passed],
            ["국면 검증", trust_summary.verification_gate.regime_passed],
            ["라벨 일치", trust_summary.verification_gate.label_matched],
          ].map(([label, ok]) => (
            <div
              key={label as string}
              className="p-3 bg-slate-50 border border-slate-200/60 rounded-xl text-center"
            >
              <div className="text-[10px] font-semibold text-slate-400">{label as string}</div>
              <div
                className={`text-xs font-extrabold mt-1 ${
                  ok ? "text-emerald-600" : "text-amber-600"
                }`}
              >
                {ok ? "통과" : "확인 필요"}
              </div>
            </div>
          ))}
        </div>
        <div className="text-[11px] text-slate-500 space-y-1 pt-1">
          <div>
            시세 출처 · <span className="font-semibold text-slate-600">{trace.generation_path.source ?? "—"}</span>
          </div>
          <div>
            해석 출처 ·{" "}
            <span className="font-semibold text-slate-600">
              {labelOf(SOURCE_LABELS, trace.generation_path.interpretation_source)}
            </span>
          </div>
          <div>
            데이터 상태 ·{" "}
            <span className="font-semibold text-slate-600">
              {labelOf(DATA_STATUS_LABELS, trace.data_quality.data_status)}
            </span>
          </div>
        </div>
      </Section>
    </div>
  );
}

function ReportSidebar({ report }: { report: TechnicalReportReadModel }) {
  const stability = report.trace_summary.stability;
  const dq = report.trace_summary.data_quality;
  const toc = [
    ["sec-summary", "핵심 요약"],
    ["sec-signals", "지표별 기술 신호"],
    ["sec-risk", "리스크 관찰점"],
    ["sec-charts", "가격 차트"],
    ["sec-verification", "검증 · 생성 경로"],
  ];
  return (
    <aside className="lg:sticky lg:top-4 space-y-4">
      <div className="bg-white rounded-2xl border border-slate-200/80 p-4 shadow-card">
        <h4 className="text-[11.5px] font-bold text-slate-400 uppercase tracking-wider mb-2.5 px-1">
          리포트 목차
        </h4>
        <nav className="space-y-0.5">
          {toc.map(([id, label]) => (
            <a
              key={id}
              href={`#${id}`}
              className="block px-2.5 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50 hover:text-indigo-600 rounded-lg transition"
            >
              {label}
            </a>
          ))}
        </nav>
      </div>

      <div className="bg-white rounded-2xl border border-slate-200/80 p-4 shadow-card space-y-2.5">
        <h4 className="text-[11.5px] font-bold text-slate-400 uppercase tracking-wider px-1">
          안정성 · 데이터 품질
        </h4>
        {stability.confidence_basis && (
          <p className="text-[11px] text-slate-500 leading-snug px-1">
            {stability.confidence_basis}
          </p>
        )}
        <div className="flex items-center gap-1.5 px-1 text-[11px] font-semibold">
          <GitFork className="w-3.5 h-3.5 text-indigo-400" />
          <span className="text-slate-600">
            검증 일관성 {stability.verification_consistent ? "일치" : "불일치"}
          </span>
        </div>
        <div className="px-1 text-[11px] text-slate-500">
          차트 {dq.chart_count}개 · {dq.limited ? "데이터 제한" : "정상"}
        </div>
      </div>
    </aside>
  );
}

export function TechnicalReportView({ reportId }: { reportId: string }) {
  const { report, loading, error, reload } = useTechnicalReport(reportId);
  const { toast } = useToast();

  const share = () => {
    if (typeof window !== "undefined") {
      navigator.clipboard?.writeText(window.location.href);
      toast("리포트 링크가 복사되었습니다");
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-8 max-w-5xl mx-auto space-y-6 screen-enter">
        <div className="flex items-center justify-between">
          <Link
            href="/library"
            className="inline-flex items-center gap-1.5 text-xs font-bold text-indigo-600 hover:text-indigo-800 transition"
          >
            <ChevronLeft className="w-4 h-4" /> 보관함으로 돌아가기
          </Link>
          {report && (
            <button
              onClick={share}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 border border-slate-200 hover:bg-slate-50 text-xs font-bold text-slate-700 rounded-xl transition"
            >
              <Share2 className="w-4 h-4" /> 공유
            </button>
          )}
        </div>

        {loading && (
          <div className="space-y-6">
            <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-6 h-48 animate-pulse" />
            <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-6 h-64 animate-pulse" />
          </div>
        )}

        {!loading && error && (
          <div className="py-16 bg-white border border-dashed border-rose-200 rounded-2xl text-center">
            <p className="text-xs font-semibold text-rose-500">
              {error.kind === "not_found"
                ? "리포트를 찾을 수 없습니다."
                : "리포트를 불러오지 못했습니다."}
            </p>
            {error.kind !== "not_found" && (
              <button
                onClick={reload}
                className="mt-3 text-xs font-bold text-indigo-600 hover:text-indigo-800 transition"
              >
                다시 시도
              </button>
            )}
          </div>
        )}

        {!loading && !error && report && (
          <>
            <TrustHeader report={report} />
            <div className="grid lg:grid-cols-[1fr_240px] gap-6 items-start">
              <ReportBody report={report} />
              <ReportSidebar report={report} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
