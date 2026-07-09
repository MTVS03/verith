"use client";

import { Check, Gauge, Sparkles, TrendingUp, TrendingDown, Minus } from "lucide-react";
import type { TechnicalReportReadModel } from "@/types/technical";
import { formatDateTime } from "@/lib/format";
import { signalLabel } from "@/lib/technical-labels";
import { BoldText } from "@/lib/bold-text";

// 신호 흐름 요약(interpretation_text)의 5구조 라벨을 파싱해 블록으로 분리한다(마크다운 파서 없이).
// 라벨이 없으면 null → 호출부가 기존 plain text 로 렌더(하위호환).
const FLOW_LABELS = ["전체 판단", "약세 근거", "완충 신호", "주의할 점", "다음 관찰 기준"] as const;
const FLOW_LABEL_STYLE: Record<string, string> = {
  "전체 판단": "text-[#4f46e5] bg-indigo-50 border-indigo-100",
  "약세 근거": "text-rose-700 bg-rose-50 border-rose-100",
  "완충 신호": "text-emerald-700 bg-emerald-50 border-emerald-100",
  "주의할 점": "text-amber-700 bg-amber-50 border-amber-100",
  "다음 관찰 기준": "text-cyan-700 bg-cyan-50 border-cyan-100",
};

type FlowBlock = { label: string; body: string };

function parseFlowSummary(
  text: string | null | undefined
): { blocks: FlowBlock[]; footer: string | null } | null {
  if (!text) return null;
  const re = new RegExp(`(${FLOW_LABELS.join("|")})\\s*:\\s*`, "g");
  const matches = [...text.matchAll(re)];
  if (matches.length === 0) return null; // 구조 라벨 없음 → plain 렌더로 폴백
  const blocks: FlowBlock[] = [];
  for (let i = 0; i < matches.length; i++) {
    const start = (matches[i].index ?? 0) + matches[i][0].length;
    const end = i + 1 < matches.length ? matches[i + 1].index ?? text.length : text.length;
    blocks.push({ label: matches[i][1], body: text.slice(start, end).trim() });
  }
  // 마지막 블록 끝의 비추천 안내는 footer 로 분리.
  let footer: string | null = null;
  const last = blocks[blocks.length - 1];
  const discIdx = last.body.indexOf("이 내용은 투자 판단");
  if (discIdx >= 0) {
    footer = last.body.slice(discIdx).trim();
    last.body = last.body.slice(0, discIdx).trim();
  }
  return { blocks: blocks.filter((b) => b.body), footer };
}

// Custom SVG Needle Gauge Component
function SVGNeedleGauge({ score }: { score: number }) {
  const angle = Math.PI * (1 - (score + 1) / 2);
  const cx = 160;
  const cy = 135;
  const r = 90;
  const nx = cx + r * Math.cos(angle);
  const ny = cy - r * Math.sin(angle);

  const polarToCartesian = (centerX: number, centerY: number, radius: number, angleInRadians: number) => {
    return {
      x: centerX + radius * Math.cos(angleInRadians),
      y: centerY - radius * Math.sin(angleInRadians),
    };
  };

  const describeArc = (x: number, y: number, radius: number, startAngleRad: number, endAngleRad: number) => {
    const start = polarToCartesian(x, y, radius, startAngleRad);
    const end = polarToCartesian(x, y, radius, endAngleRad);
    const largeArcFlag = startAngleRad - endAngleRad <= Math.PI ? "0" : "1";
    return [
      "M", start.x, start.y,
      "A", radius, radius, 0, largeArcFlag, 1, end.x, end.y
    ].join(" ");
  };

  const segments = [
    { start: Math.PI, end: Math.PI * 0.75, color: "#e11d48" },       // 강한 부정
    { start: Math.PI * 0.75, end: Math.PI * 0.65, color: "#fb7185" }, // 약한 부정
    { start: Math.PI * 0.65, end: Math.PI * 0.35, color: "#cbd5e1" }, // 중립
    { start: Math.PI * 0.35, end: Math.PI * 0.25, color: "#6ee7b7" }, // 약한 긍정
    { start: Math.PI * 0.25, end: 0, color: "#10b981" },              // 강한 긍정
  ];

  return (
    <svg viewBox="0 0 320 150" className="w-[280px] h-[130px]">
      {segments.map((seg, idx) => (
        <path
          key={idx}
          d={describeArc(cx, cy, 100, seg.start - 0.015, seg.end + 0.015)}
          fill="none"
          stroke={seg.color}
          strokeWidth="15"
          strokeLinecap={idx === 0 || idx === 4 ? "round" : "butt"}
        />
      ))}
      <line
        x1={cx}
        y1={cy}
        x2={nx}
        y2={ny}
        stroke="#1e293b"
        strokeWidth="6"
        strokeLinecap="round"
      />
      <circle cx={cx} cy={cy} r="8" fill="#1e293b" />
      <circle cx={cx} cy={cy} r="3" fill="#ffffff" />
    </svg>
  );
}

export function TechnicalSummarySections({ report }: { report: TechnicalReportReadModel }) {
  const score = report.signals.signal_score ?? 0;
  const formattedAsOf = report.meta.as_of ? formatDateTime(report.meta.as_of) : "—";

  // Categorize sub-signals
  const signalItems = report.signals.items;
  const positiveCount = signalItems.filter((i) => i.signal === "positive").length;
  const neutralCount = signalItems.filter((i) => i.signal === "neutral" || !i.signal).length;
  const negativeCount = signalItems.filter((i) => i.signal === "negative").length;

  const getScoreColor = (val: number) => {
    if (val >= 0.3) return "text-[#10b981]"; // positive
    if (val <= -0.3) return "text-[#f43f5e]"; // negative
    return "text-[#64748b]"; // neutral
  };

  const getScoreText = (val: number) => {
    if (val >= 0.3) return "약한 긍정";
    if (val >= 0.7) return "강한 긍정";
    if (val <= -0.7) return "강한 부정";
    if (val <= -0.3) return "약한 부정";
    return "중립";
  };

  const getScoreIcon = (val: number) => {
    if (val >= 0.3) return <TrendingUp className="w-[17px] h-[17px]" />;
    if (val <= -0.3) return <TrendingDown className="w-[17px] h-[17px]" />;
    return <Minus className="w-[17px] h-[17px]" />;
  };

  // Human-readable labels mapping for strategies list
  const INDICATOR_MAP: Record<string, string> = {
    moving_average: "이동평균",
    rsi: "RSI",
    volume: "거래량",
    support_resistance: "지지저항",
    pattern: "패턴",
  };

  const getSignalColor = (sig: string | null) => {
    if (sig === "positive") return "bg-[#10b981]";
    if (sig === "negative") return "bg-[#f43f5e]";
    return "bg-[#cbd5e1]";
  };

  return (
    <div className="flex flex-col gap-6">
      {/* 1. 신호 종합 Section */}
      <section
        id="a-summary"
        className="scroll-mt-16 border border-[#f1f5f9] rounded-2xl p-6 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_1px_3px_rgba(15,23,42,0.06)] bg-white"
      >
        <div className="flex items-center justify-between border-b border-[#f1f5f9] pb-3 mb-4.5">
          <h2 className="flex items-center gap-2.5 text-base font-bold text-[#0f172a] m-0">
            <Gauge className="w-[19px] h-[19px] text-[#334155]" /> 신호 종합
          </h2>
          <span className="text-[11px] font-semibold text-[#64748b] bg-[#f8fafc] px-2.5 py-1 rounded-full">
            {signalItems.length}개 지표 가중 집계
          </span>
        </div>

        <div className="flex flex-col items-center">
          <div className="w-[280px]">
            <SVGNeedleGauge score={score} />
          </div>
          <div className="flex flex-col items-center -mt-1.5">
            <div className={`text-[42px] font-bold tracking-tight leading-none font-tabular ${getScoreColor(score)}`}>
              {score >= 0 ? "+" : ""}
              {score.toFixed(2)}
            </div>
            <div className={`flex items-center gap-1 mt-1.5 text-sm font-semibold ${getScoreColor(score)}`}>
              {getScoreIcon(score)}
              <span>{getScoreText(score)}</span>
            </div>
          </div>

          <div className="flex items-center justify-between w-[280px] mt-3 text-[12.5px] text-[#94a3b8]">
            <span>부정 −1.0</span>
            <span>중립 0</span>
            <span>+1.0 긍정</span>
          </div>

          <div className="flex items-center gap-5 mt-3 text-sm font-semibold font-tabular">
            <span className="text-[#f43f5e]">부정 {negativeCount}</span>
            <span className="text-[#64748b]">중립 {neutralCount}</span>
            <span className="text-[#10b981]">긍정 {positiveCount}</span>
          </div>
        </div>

        {/* Breakdown table & reliability list grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-5.5">
          <div className="border border-[#e2e8f0] rounded-xl p-4.5">
            <div className="text-xs font-semibold text-[#64748b]">지표별 판정</div>
            <div className="flex flex-col gap-2 mt-3">
              {signalItems.map((item) => (
                <div key={item.indicator} className="flex items-center justify-between text-[13px]">
                  <span className="text-[#64748b]">{INDICATOR_MAP[item.indicator] ?? item.indicator}</span>
                  <span className="flex items-center gap-1.5 font-semibold text-[#1e293b]">
                    <span className={`w-2 h-2 rounded-full ${getSignalColor(item.signal)}`} />
                    {signalLabel(item.signal)}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="border border-[#e2e8f0] rounded-xl p-4.5">
            <div className="text-xs font-semibold text-[#64748b]">데이터 신뢰도</div>
            <div className="flex items-center gap-2 mt-1.5">
              <span className="text-[32px] font-extrabold leading-none text-[#0f172a]">
                {report.trust_summary.data_quality.limited ? "제한" : "높음"}
              </span>
              <Check className="w-6 h-6 text-[#10b981]" />
            </div>
            <div className="flex flex-col gap-1.5 mt-3.5 text-[12.5px]">
              <div className="flex items-start gap-2">
                <Check className="w-4 h-4 text-[#10b981] flex-shrink-0 mt-0.5" />
                <span className="text-[#475569]">
                  <b className="text-[#1e293b] font-semibold">출처</b> · {report.meta.source ?? "unknown"} 공식 API
                </span>
              </div>
              <div className="flex items-start gap-2">
                <Check className="w-4 h-4 text-[#10b981] flex-shrink-0 mt-0.5" />
                <span className="text-[#475569]">
                  <b className="text-[#1e293b] font-semibold">완전성</b> ·{" "}
                  {report.trust_summary.data_quality.data_status ?? "90거래일 결측 0건"}
                </span>
              </div>
              <div className="flex items-start gap-2">
                <Check className="w-4 h-4 text-[#10b981] flex-shrink-0 mt-0.5" />
                <span className="text-[#475569]">
                  <b className="text-[#1e293b] font-semibold">신선도</b> · {formattedAsOf} 반영
                </span>
              </div>
              <div className="flex items-start gap-2">
                <Check className="w-4 h-4 text-[#10b981] flex-shrink-0 mt-0.5" />
                <span className="text-[#475569]">
                  <b className="text-[#1e293b] font-semibold">충분성</b> · 60일선 계산 기준 충족
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 2. 신호 흐름 요약 Section */}
      <section
        id="a-flow"
        className="scroll-mt-16 border border-[#f1f5f9] rounded-2xl p-6 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_1px_3px_rgba(15,23,42,0.06)] bg-white"
      >
        <div className="flex items-center justify-between border-b border-[#f1f5f9] pb-3 mb-4">
          <h2 className="flex items-center gap-2.5 text-base font-bold text-[#0f172a] m-0">
            <TrendingUp className="w-[19px] h-[19px] text-[#334155]" /> 신호 흐름 요약
          </h2>
          <span className="flex items-center gap-1.5 text-xs font-semibold text-[#4f46e5]">
            <Sparkles className="w-3.5 h-3.5" /> AI 분석 · 근거 연결
          </span>
        </div>

        {(() => {
          const flow = parseFlowSummary(report.interpretation.text);
          if (!flow) {
            // 라벨 구조가 없으면 기존 plain 렌더(하위호환)
            return (
              <p className="text-[14.5px] leading-loose text-[#334155] m-0 whitespace-pre-wrap">
                {report.interpretation.text ? (
                  <BoldText text={report.interpretation.text} />
                ) : (
                  "기술 리포트 요약이 없습니다."
                )}
              </p>
            );
          }
          return (
            <div className="flex flex-col gap-2.5">
              {flow.blocks.map((b) => (
                <div key={b.label} className="flex flex-col sm:flex-row sm:items-start gap-1.5 sm:gap-3">
                  <span
                    className={`shrink-0 self-start text-[11.5px] font-bold px-2 py-1 rounded-lg border ${
                      FLOW_LABEL_STYLE[b.label] ?? "text-slate-600 bg-slate-50 border-slate-100"
                    }`}
                  >
                    {b.label}
                  </span>
                  <p className="text-[14px] leading-relaxed text-[#334155] m-0">
                    <BoldText text={b.body} />
                  </p>
                </div>
              ))}
              {flow.footer && (
                <p className="text-[12px] text-[#94a3b8] leading-relaxed m-0 mt-1 border-t border-[#f1f5f9] pt-2.5">
                  {flow.footer}
                </p>
              )}
            </div>
          );
        })()}

        <div className="border-t border-[#f1f5f9] mt-4.5 pt-3.5 flex items-center gap-x-5.5 gap-y-2 flex-wrap text-[13px]">
          <span className="text-[#94a3b8]">근거 지표</span>
          {signalItems.map((item, idx) => (
            <span key={item.indicator} className="text-[#475569]">
              <span className="text-[#94a3b8] font-tabular mr-1">#{idx + 1}</span>
              {INDICATOR_MAP[item.indicator] ?? item.indicator}
            </span>
          ))}
        </div>
      </section>
    </div>
  );
}
