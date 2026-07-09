"use client";

import { createElement, useState } from "react";
import {
  Calculator,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  ChevronUp,
  ChevronDown,
  TrendingUp,
  Gauge,
  BarChart3,
  Ruler,
  CandlestickChart,
} from "lucide-react";
import type { IndicatorCard } from "@/types/technical";
import { formatNumber } from "@/lib/format";

// Format Volume helper to "만주" units
function formatVolume(val: number | null): string {
  if (val === null) return "—";
  const manJu = Math.round(val / 10000);
  return `${manJu.toLocaleString()}만주`;
}

// SVG RSI Sparkline (30 points)
function RsiSparkline({ points }: { points: Array<{ date: string; value: number }> }) {
  if (!points || points.length === 0) return null;
  const width = 160;
  const height = 30;
  const padding = 2;
  const values = points.map((p) => p.value);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 100);
  const range = max - min || 1;

  const pathPoints = points.map((p, idx) => {
    const x = padding + (idx / (points.length - 1)) * (width - padding * 2);
    const y = height - padding - ((p.value - min) / range) * (height - padding * 2);
    return `${x},${y}`;
  });

  return (
    <svg width={width} height={height} className="overflow-visible">
      <polyline
        fill="none"
        stroke="#f97316"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={pathPoints.join(" ")}
      />
    </svg>
  );
}

// SVG Volume Sparkline (8 bars)
function VolumeSparkline({ bars }: { bars: Array<{ date: string; volume: number }> }) {
  if (!bars || bars.length === 0) return null;
  const width = 120;
  const height = 28;
  const barWidth = 9;
  const gap = 4;
  const values = bars.map((b) => b.volume);
  const max = Math.max(...values) || 1;

  return (
    <svg width={width} height={height} className="overflow-visible flex items-end">
      {bars.map((bar, idx) => {
        const barHeight = (bar.volume / max) * height;
        const x = idx * (barWidth + gap);
        const y = height - barHeight;
        // Last bar is green (active), others are gray
        const isLast = idx === bars.length - 1;
        const fill = isLast ? "#10b981" : "#cbd5e1";
        return (
          <rect
            key={idx}
            x={x}
            y={y}
            width={barWidth}
            height={barHeight}
            fill={fill}
            rx={1.5}
          />
        );
      })}
    </svg>
  );
}

// Progress Bar Helper
function ProgressBar({
  value,
  max,
  label,
  colorClass,
}: {
  value: number;
  max: number;
  label: string;
  colorClass: string;
}) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div className="w-full flex flex-col gap-1.5">
      <div className="flex justify-between items-center text-xs font-semibold text-[#475569]">
        <span>{label}</span>
        <span className="font-tabular font-bold">{formatVolume(value)}</span>
      </div>
      <div className="w-full h-1.5 bg-[#f1f5f9] rounded-full overflow-hidden">
        <div className={`h-full ${colorClass} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function IndicatorCardComponent({
  card,
  index,
}: {
  card: IndicatorCard;
  index: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const { indicator, title, signal, signal_label, weight, llm_detail, detail_source, detail_reason, detail_caution, detail_watchpoint, verified, code_metrics, calc_basis } = card;

  // Signal color styling
  const getSignalStyle = (sig: string | null) => {
    if (sig === "positive") {
      return "text-[#10b981] bg-[rgba(16,185,129,0.10)]";
    }
    if (sig === "negative") {
      return "text-[#f43f5e] bg-[rgba(244,63,94,0.10)]";
    }
    return "text-[#64748b] bg-slate-100";
  };

  // Header icon selector
  const getHeaderIcon = (ind: string) => {
    switch (ind) {
      case "moving_average":
        return TrendingUp;
      case "rsi":
        return Gauge;
      case "volume":
        return BarChart3;
      case "support_resistance":
        return Ruler;
      case "pattern":
        return CandlestickChart;
      default:
        return TrendingUp;
    }
  };

  // 렌더 중 Capitalized 컴포넌트 변수 생성(react-hooks/static-components) 회피 — element 로 만든다.
  const headerIconEl = createElement(getHeaderIcon(indicator), {
    className: "w-4 h-4 text-[#475569]",
  });

  return (
    <div className="border border-[#e2e8f0] rounded-2xl bg-white shadow-[0_1px_2px_rgba(15,23,42,0.03)] p-6 flex flex-col gap-4">
      {/* 1. Header Area */}
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold text-[#94a3b8] tracking-wider leading-none">
            {index + 1}
          </span>
          <span className="text-[17px] font-extrabold text-[#0f172a] tracking-tight">
            {title}
          </span>
          <span className={`text-[11px] font-bold px-2 py-0.5 rounded-md ${getSignalStyle(signal)}`}>
            {signal_label ?? "중립"}
          </span>
        </div>
        <span className="text-[11.5px] font-semibold text-[#94a3b8]">
          가중치 <b className="text-[#0f172a] font-bold font-tabular">{weight?.toFixed(2) ?? "0.10"}</b>
        </span>
      </div>

      {/* 2. Code calculation metrics chips row */}
      {code_metrics.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11.5px] font-bold text-[#059669] bg-[rgba(16,185,129,0.06)] px-2 py-0.5 rounded flex items-center gap-1">
            <Calculator className="w-3.5 h-3.5" /> 코드 계산
          </span>
          {code_metrics.map((m) => (
            <span
              key={m}
              className="text-[11px] font-semibold px-2.5 py-1 bg-[#f8fafc] border border-[#e2e8f0] rounded-lg text-[#475569] font-tabular"
            >
              {m}
            </span>
          ))}
        </div>
      )}

      {/* 3. LLM narrative box */}
      {llm_detail && (
        <div className="border-l-[3px] border-[#4f46e5] bg-[rgba(79,70,229,0.015)] rounded-r-xl p-4.5">
          <div className="flex justify-between items-center mb-2.5">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-[#4f46e5] flex items-center gap-1">
                <Sparkles className="w-3.5 h-3.5" /> AI 분석
              </span>
              {verified ? (
                <span className="text-[10px] font-bold text-[#10b981] bg-[rgba(16,185,129,0.08)] px-1.5 py-0.5 rounded flex items-center gap-0.5">
                  <CheckCircle2 className="w-3 h-3" /> 검증됨
                </span>
              ) : (
                <span className="text-[10px] font-bold text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded flex items-center gap-0.5">
                  <AlertCircle className="w-3 h-3" /> 주의
                </span>
              )}
            </div>
            <span className="text-[10.5px] font-semibold text-[#94a3b8]">
              출처: {detail_source === "template_fallback" ? "기본 서술" : "AI 분석"}
            </span>
          </div>
          <p className="text-[13.5px] leading-relaxed text-[#334155] m-0">
            {llm_detail}
          </p>
          {/* 지표별 설명 확장(AI additive): 왜/주의/관찰 — 값 없으면 해당 줄 생략(null-safe) */}
          {(detail_reason || detail_caution || detail_watchpoint) && (
            <div className="mt-3 flex flex-col gap-2 border-t border-[rgba(79,70,229,0.08)] pt-3">
              {detail_reason && (
                <div className="flex gap-2 text-[12.5px] leading-relaxed">
                  <span className="shrink-0 font-bold text-[#4f46e5]">왜</span>
                  <span className="text-[#475569]">{detail_reason}</span>
                </div>
              )}
              {detail_caution && (
                <div className="flex gap-2 text-[12.5px] leading-relaxed">
                  <span className="shrink-0 font-bold text-amber-600">주의</span>
                  <span className="text-[#475569]">{detail_caution}</span>
                </div>
              )}
              {detail_watchpoint && (
                <div className="flex gap-2 text-[12.5px] leading-relaxed">
                  <span className="shrink-0 font-bold text-[#0891b2]">관찰</span>
                  <span className="text-[#475569]">{detail_watchpoint}</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 4. Toggle expanded basis details trigger */}
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 self-end text-[12px] font-bold text-[#4f46e5] hover:text-[#4338ca] transition-colors"
      >
        {expanded ? (
          <>
            접기 <ChevronUp className="w-4 h-4" />
          </>
        ) : (
          <>
            자세히 보기 <ChevronDown className="w-4 h-4" />
          </>
        )}
      </button>

      {/* 5. Expanded detailed basis calculations (calc_basis) */}
      {expanded && calc_basis && (
        <div className="border-t border-[#f1f5f9] pt-5 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-[#0f172a] flex items-center gap-1.5">
              {headerIconEl} 계산 근거
            </span>
            <span className="text-[10.5px] font-bold text-[#059669] bg-[rgba(16,185,129,0.08)] px-2 py-0.5 rounded border border-[rgba(16,185,129,0.15)]">
              결정론 계산
            </span>
          </div>

          <div className="flex flex-col gap-3">
            {/* 1. 이동평균 (moving_average) details */}
            {indicator === "moving_average" && (
              <>
                {/* Related Cross Event */}
                {(() => {
                  const cross = calc_basis.related_annotations?.find(
                    (a) => a.kind === "golden_cross" || a.kind === "dead_cross"
                  );
                  if (!cross) return null;
                  return (
                    <div className="flex justify-between items-center text-[12.5px]">
                      <span className="text-[#64748b]">{cross.label || "골든/데드크로스"} 발생일</span>
                      <span className="font-bold text-[#334155] flex items-center gap-1 font-tabular">
                        {cross.date?.replace(/-/g, ".")}
                        <span className="text-xs text-[#94a3b8] font-semibold ml-0.5">
                          {cross.meta?.pair ?? "5MA▲20MA"}
                        </span>
                      </span>
                    </div>
                  );
                })()}

                {/* 20MA Disparity */}
                {calc_basis.disparity_20_pct !== null && (
                  <div className="flex justify-between items-center text-[12.5px]">
                    <span className="text-[#64748b]">20일 이격도</span>
                    <span className="font-bold text-[#334155] font-tabular">
                      {calc_basis.disparity_20_pct >= 0 ? "+" : ""}
                      {calc_basis.disparity_20_pct.toFixed(1)}%
                      <span className="text-xs text-[#94a3b8] font-semibold ml-1.5">
                        현재가 / 20MA
                      </span>
                    </span>
                  </div>
                )}

                {/* Alignment */}
                {calc_basis.alignment && (
                  <div className="flex justify-between items-center text-[12.5px]">
                    <span className="text-[#64748b]">정배열 여부</span>
                    <span className="font-bold text-[#334155]">
                      {calc_basis.alignment}
                      <span className="text-xs text-[#94a3b8] font-semibold ml-1.5 font-tabular">
                        5 &gt; 20 &gt; 60
                      </span>
                    </span>
                  </div>
                )}

                {/* Daily MA Table */}
                {calc_basis.recent_ma && calc_basis.recent_ma.length > 0 && (
                  <div className="border border-[#e2e8f0] rounded-lg overflow-hidden mt-2">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="bg-[#f8fafc] border-b border-[#e2e8f0] text-[#64748b] font-semibold">
                          <th className="p-2">일자</th>
                          <th className="p-2 text-right">5MA</th>
                          <th className="p-2 text-right">20MA</th>
                          <th className="p-2 text-right">60MA</th>
                        </tr>
                      </thead>
                      <tbody>
                        {calc_basis.recent_ma.slice(0, 8).map((row, idx) => {
                          const dateStr = row.date ? row.date.slice(5).replace("-", ".") : "—";
                          return (
                            <tr key={idx} className="border-b border-[#f1f5f9] last:border-b-0 text-[#475569]">
                              <td className="p-2 font-semibold font-tabular">{dateStr}</td>
                              <td className="p-2 text-right font-tabular">
                                {row.ma5 ? formatNumber(row.ma5) : ""}
                              </td>
                              <td className="p-2 text-right font-bold text-[#4f46e5] font-tabular">
                                {row.ma20 ? formatNumber(row.ma20) : ""}
                              </td>
                              <td className="p-2 text-right font-tabular">
                                {row.ma60 ? formatNumber(row.ma60) : ""}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}

            {/* 2. RSI (rsi) details */}
            {indicator === "rsi" && (
              <>
                {/* RSI Sparkline path */}
                {calc_basis.rsi_recent_points && calc_basis.rsi_recent_points.length > 0 && (
                  <div className="flex justify-between items-center text-[12.5px] border-b border-[#f1f5f9] pb-3 mb-1">
                    <span className="text-[#64748b]">최근 14일 RSI 추이</span>
                    <RsiSparkline points={calc_basis.rsi_recent_points} />
                  </div>
                )}

                <div className="flex justify-between items-center text-[12.5px]">
                  <span className="text-[#64748b]">계산 기준</span>
                  <span className="font-bold text-[#334155]">
                    {calc_basis.rsi_period ?? "14"}일 종가 기반 RSI
                  </span>
                </div>

                <div className="flex justify-between items-center text-[12.5px]">
                  <span className="text-[#64748b]">현재 RSI</span>
                  <span className="font-bold text-[#334155] font-tabular">
                    {calc_basis.current_value?.toFixed(1) ?? "—"}
                    <span className="text-xs text-[#94a3b8] font-semibold ml-1.5">
                      과매수({calc_basis.overbought ?? "70"}) 근접
                    </span>
                  </span>
                </div>

                {/* Oversold annotations */}
                {(() => {
                  const oSold = calc_basis.related_annotations?.find((a) => a.kind === "rsi_oversold");
                  return (
                    <div className="flex justify-between items-center text-[12.5px]">
                      <span className="text-[#64748b]">최근 과매도 도달</span>
                      <span className="font-bold text-[#334155] font-tabular">
                        {oSold ? (
                          <>
                            RSI {oSold.meta?.rsi ?? "28"}
                            <span className="text-xs text-[#94a3b8] font-semibold ml-1.5">
                              {oSold.date?.replace(/-/g, ".")}
                            </span>
                          </>
                        ) : (
                          "없음"
                        )}
                      </span>
                    </div>
                  );
                })()}

                {/* Overbought annotations */}
                {(() => {
                  const oBought = calc_basis.related_annotations?.find((a) => a.kind === "rsi_overbought");
                  return (
                    <div className="flex justify-between items-center text-[12.5px]">
                      <span className="text-[#64748b]">최근 과매수 도달</span>
                      <span className="font-bold text-[#334155] font-tabular">
                        {oBought ? (
                          <>
                            RSI {oBought.meta?.rsi ?? "72"}
                            <span className="text-xs text-[#94a3b8] font-semibold ml-1.5">
                              {oBought.date?.replace(/-/g, ".")}
                            </span>
                          </>
                        ) : (
                          <span className="text-xs text-[#cbd5e1] font-semibold">없음 최근 90일</span>
                        )}
                      </span>
                    </div>
                  );
                })()}
              </>
            )}

            {/* 3. 거래량 (volume) details */}
            {indicator === "volume" && (
              <>
                {/* Volume Sparkline bars */}
                {calc_basis.volume_recent_bars && calc_basis.volume_recent_bars.length > 0 && (
                  <div className="flex justify-between items-end text-[12.5px] border-b border-[#f1f5f9] pb-3 mb-1">
                    <span className="text-[#64748b]">최근 8일 거래량(만주)</span>
                    <VolumeSparkline bars={calc_basis.volume_recent_bars} />
                  </div>
                )}

                {/* Progress bars for volume comparison */}
                {calc_basis.current_volume !== null && calc_basis.avg_volume !== null && (
                  <div className="flex flex-col gap-3 my-1">
                    {(() => {
                      const maxVol = Math.max(calc_basis.current_volume || 0, calc_basis.avg_volume || 0) || 1;
                      return (
                        <>
                          <ProgressBar
                            value={calc_basis.current_volume}
                            max={maxVol}
                            label="당일"
                            colorClass="bg-[#10b981]"
                          />
                          <ProgressBar
                            value={calc_basis.avg_volume}
                            max={maxVol}
                            label="20일 평균"
                            colorClass="bg-[#94a3b8]"
                          />
                        </>
                      );
                    })()}
                  </div>
                )}

                {calc_basis.relative_volume !== null && (
                  <div className="flex justify-between items-center text-[12.5px] mt-1.5">
                    <span className="text-[#64748b]">상대 거래량</span>
                    <span className="font-bold text-[#334155] font-tabular">
                      {calc_basis.relative_volume.toFixed(2)}배
                      <span className="text-xs text-[#94a3b8] font-semibold ml-1.5">
                        당일 / 20일평균
                      </span>
                    </span>
                  </div>
                )}
              </>
            )}

            {/* 4. 지지저항 (support_resistance) details */}
            {indicator === "support_resistance" && (
              <>
                <div className="flex justify-between items-center text-[12.5px]">
                  <span className="text-[#64748b]">지지선</span>
                  <span className="font-bold text-[#334155] font-tabular">
                    {calc_basis.support ? `${formatNumber(calc_basis.support)}원` : "—"}
                    <span className="text-xs text-[#94a3b8] font-semibold ml-1.5">
                      최근 6개월 저점 클러스터
                    </span>
                  </span>
                </div>

                {/* Support touch count annotations */}
                {(() => {
                  const touches = calc_basis.related_annotations?.filter((a) => a.kind === "support_touch") || [];
                  const dates = touches.map((t) => t.date ? t.date.slice(5).replace("-", "/") : "").filter(Boolean);
                  return (
                    <div className="flex justify-between items-center text-[12.5px]">
                      <span className="text-[#64748b]">지지 터치</span>
                      <span className="font-bold text-[#334155] font-tabular">
                        {touches.length}회
                        {dates.length > 0 && (
                          <span className="text-xs text-[#94a3b8] font-semibold ml-1.5 font-tabular">
                            {dates.join(" · ")}
                          </span>
                        )}
                      </span>
                    </div>
                  );
                })()}

                <div className="flex justify-between items-center text-[12.5px]">
                  <span className="text-[#64748b]">저항선</span>
                  <span className="font-bold text-[#334155] font-tabular">
                    {calc_basis.resistance ? `${formatNumber(calc_basis.resistance)}원` : "—"}
                    <span className="text-xs text-[#94a3b8] font-semibold ml-1.5">
                      직전 고점 영역
                    </span>
                  </span>
                </div>

                {/* Resistance touch count annotations */}
                {(() => {
                  const touches = calc_basis.related_annotations?.filter((a) => a.kind === "resistance_touch") || [];
                  const dates = touches.map((t) => t.date ? t.date.slice(5).replace("-", "/") : "").filter(Boolean);
                  return (
                    <div className="flex justify-between items-center text-[12.5px]">
                      <span className="text-[#64748b]">저항 터치</span>
                      <span className="font-bold text-[#334155] font-tabular">
                        {touches.length}회
                        {dates.length > 0 && (
                          <span className="text-xs text-[#94a3b8] font-semibold ml-1.5 font-tabular">
                            {dates.join(" · ")}
                          </span>
                        )}
                      </span>
                    </div>
                  );
                })()}

                <div className="flex justify-between items-center text-[12.5px]">
                  <span className="text-[#64748b]">현재가 위치</span>
                  <span className="font-bold text-[#334155] font-tabular">
                    {calc_basis.position ?? "—"}
                    {calc_basis.support && calc_basis.resistance && (
                      <span className="text-xs text-[#94a3b8] font-semibold ml-1.5 font-tabular">
                        {formatNumber(calc_basis.support)} ~ {formatNumber(calc_basis.resistance)}
                      </span>
                    )}
                  </span>
                </div>
              </>
            )}

            {/* 5. 패턴 (pattern) details — cup_handle 후보가 있을 때만 구조화 표시.
                값은 annotation meta 그대로(없는 값은 지어내지 않고 해당 행 생략). 후보가 없으면 위의
                공통 llm_detail/code_metrics 서술로 충분하므로 별도 하드코딩 행을 만들지 않는다. */}
            {indicator === "pattern" && card.pattern_candidates && card.pattern_candidates.length > 0 && (
              <>
                {card.pattern_candidates.map((cand, idx) => {
                  const meta = (cand.meta ?? {}) as Record<string, unknown>;
                  const pct = (v: unknown) =>
                    typeof v === "number" ? `${Math.round(v * 100)}%` : null;
                  const depth = pct(meta.cup_depth_pct);
                  const pullback = pct(meta.handle_pullback_pct);
                  const stageRaw = typeof meta.candidate_stage === "string" ? meta.candidate_stage : "";
                  const stageLabel =
                    stageRaw === "handle_forming" ? "핸들 형성 중"
                    : stageRaw === "cup_forming" ? "컵 형성 중"
                    : stageRaw === "confirmed" ? "형성 완료"
                    : stageRaw || "후보";
                  const impLabel =
                    cand.importance === "high" ? "높음" : cand.importance === "low" ? "낮음" : "보통";
                  const volConfirmed = meta.volume_confirmed === true;
                  return (
                    <div key={idx} className="border-b border-[#f1f5f9] last:border-b-0 pb-3 last:pb-0 flex flex-col gap-1.5 text-[12.5px]">
                      <div className="flex justify-between items-center">
                        <span className="text-[#64748b]">감지 형태</span>
                        <span className="font-bold text-[#334155]">
                          {cand.label}
                          <span className="text-xs text-[#94a3b8] font-semibold ml-1.5">
                            Cup &amp; Handle 후보
                          </span>
                        </span>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-[#64748b]">상태</span>
                        <span className="font-bold text-[#334155]">{stageLabel}</span>
                      </div>
                      {depth && (
                        <div className="flex justify-between items-center">
                          <span className="text-[#64748b]">컵 깊이</span>
                          <span className="font-bold text-[#334155] font-tabular">{depth}</span>
                        </div>
                      )}
                      {pullback && (
                        <div className="flex justify-between items-center">
                          <span className="text-[#64748b]">핸들 눌림</span>
                          <span className="font-bold text-[#334155] font-tabular">{pullback}</span>
                        </div>
                      )}
                      <div className="flex justify-between items-center">
                        <span className="text-[#64748b]">신뢰도(중요도)</span>
                        <span className="font-bold text-[#334155]">
                          {impLabel}
                          <span
                            className={`text-xs font-semibold ml-1.5 ${
                              volConfirmed ? "text-emerald-600" : "text-amber-600"
                            }`}
                          >
                            {volConfirmed ? "거래량 수반" : "거래량 미수반"}
                          </span>
                        </span>
                      </div>
                    </div>
                  );
                })}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
