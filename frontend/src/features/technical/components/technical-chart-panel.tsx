"use client";

import { useMemo, useState } from "react";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ReferenceArea,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { MousePointerClick, Info, GitCommitHorizontal, History } from "lucide-react";

import type { TechnicalChartsReadModel } from "@/types/technical";
import { formatNumber } from "@/lib/format";
import {
  type ChartAnnotation,
  candleDate,
  computeHighLow,
  formatChartDate,
  getCupHandleGeometry,
  getPriceChartAnnotations,
  getRsiAnnotations,
  partitionAnnotationsByKind,
} from "@/lib/technical-chart";

function findClosestDateIndex(dateStr: string | null | undefined, data: PricePoint[]): number {
  if (!dateStr || data.length === 0) return -1;
  const exactIdx = data.findIndex((p) => p.date === dateStr);
  if (exactIdx !== -1) return exactIdx;
  const targetTime = new Date(dateStr).getTime();
  if (isNaN(targetTime)) return -1;
  let closestIdx = 0;
  let minDiff = Infinity;
  for (let i = 0; i < data.length; i++) {
    const cellTime = new Date(data[i].date).getTime();
    if (isNaN(cellTime)) continue;
    const diff = Math.abs(cellTime - targetTime);
    if (diff < minDiff) {
      minDiff = diff;
      closestIdx = i;
    }
  }
  return closestIdx;
}

type PricePoint = {
  /** x축 카테고리 = 유일한 전체 날짜(주봉/월봉의 MM/DD 중복으로 마커가 엉뚱한 곳에 찍히는 것 방지) */
  date: string;
  close: number;
  open?: number;
  high?: number;
  low?: number;
  volume: number;
  [key: `ma_${number}`]: number | null;
  cup_curve?: number | null;
};

// chart_data 는 일봉/주봉/월봉 ↔ 분봉 스키마가 달라(느슨하게) 접근한다. 값 의미는 백엔드 그대로 신뢰.
type RawCandle = {
  date?: string;
  timestamp?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};
type MaOverlay = { window: number; points: Array<{ date: string; value: number }> };
type SrLine = { type: "support" | "resistance"; price: number };
type VolumeBar = { date?: string; timestamp?: string; volume: number; is_spike?: boolean };
type RsiPoint = { date?: string; timestamp?: string; value: number };
type ChartDataLoose = {
  candles?: RawCandle[];
  overlays?: { moving_average?: MaOverlay[]; support_resistance?: SrLine[] };
  subcharts?: {
    rsi?: { overbought?: number; oversold?: number; points?: RsiPoint[] };
    volume?: { bars?: VolumeBar[] };
  };
  rsi?: RsiPoint[];
};

const PERIOD_MAP: Record<string, string> = {
  "1d": "1일",
  "1min": "1일",
  "1m": "1개월",
  "3m": "3개월",
  "1y": "1년",
  "5y": "5년",
};

export function TechnicalChartPanel({ charts }: { charts: TechnicalChartsReadModel }) {
  const PERIOD_ORDER = ["1d", "1day", "1m", "3m", "1y", "5y"];
  const periods = [...charts.available_periods].sort((a, b) => {
    const idxA = PERIOD_ORDER.indexOf(a);
    const idxB = PERIOD_ORDER.indexOf(b);
    const orderA = idxA !== -1 ? idxA : 999;
    const orderB = idxB !== -1 ? idxB : 999;
    return orderA - orderB;
  });
  const [activePeriod, setActivePeriod] = useState<string>(
    periods.includes("1y") ? "1y" : periods[0]
  );

  // Layout toggles
  const [showMa, setShowMa] = useState(true);
  const [showSr, setShowSr] = useState(true);
  const [showRsi, setShowRsi] = useState(true);
  const [showVolume, setShowVolume] = useState(true);

  // Derived candle unit label (period → unit, read-only)
  const getCandleUnitLabel = (unit: string | null | undefined): string => {
    if (unit === "1min") return "분봉";
    if (unit === "W") return "주봉";
    if (unit === "M") return "월봉";
    return "일봉";
  };

  // Indicator signal toggles
  const [showGoldenCross, setShowGoldenCross] = useState(false);
  const [showSrTouch, setShowSrTouch] = useState(false);
  const [showVolumeSpike, setShowVolumeSpike] = useState(false);
  const [showPatternArea, setShowPatternArea] = useState(false);

  const activeChart = useMemo(
    () => charts.charts.find((item) => item.period === activePeriod) ?? charts.charts[0],
    [activePeriod, charts.charts]
  );

  const candleUnitLabel = getCandleUnitLabel(activeChart?.candle_unit);
  const isIntraday = activeChart?.period === "1d";
  const activeData = activeChart?.chart_data as ChartDataLoose | null | undefined;

  // 원시 annotation(백엔드 데이터 그대로 신뢰) — kind별 좌표 규칙은 헬퍼가 분기한다.
  const annotations = useMemo<ChartAnnotation[]>(
    () => ((activeChart?.annotations ?? []) as unknown as ChartAnnotation[]),
    [activeChart]
  );

  const grouped = useMemo(() => partitionAnnotationsByKind(annotations), [annotations]);
  // 가격 차트용: cross/volume_spike(종가) + S/R 터치(레벨). RSI는 여기서 제외(서브차트 전용).
  const priceAnnotations = useMemo(() => getPriceChartAnnotations(annotations), [annotations]);
  const rsiAnnotations = useMemo(() => getRsiAnnotations(annotations), [annotations]);
  const cupHandles = useMemo(() => getCupHandleGeometry(annotations), [annotations]);

  const crossMarkers = priceAnnotations.filter(
    (a) => a.kind === "golden_cross" || a.kind === "dead_cross"
  );
  const volumeSpikeMarkers = priceAnnotations.filter((a) => a.kind === "volume_spike");
  const srMarkers = priceAnnotations.filter((a) => a.marker === "level");

  const hasCross = grouped.cross.length > 0;
  const hasSrTouch = grouped.srTouch.length > 0;
  const hasVolumeSpike = grouped.volumeSpike.length > 0;
  const hasPattern = cupHandles.length > 0;
  // cup_handle 은 1y/5y 에서만 렌더(백엔드 정책과 동일).
  const patternRenderable = hasPattern && (activePeriod === "1y" || activePeriod === "5y");

  const dateLabel = (d?: string) => (d ? ` ${formatChartDate(d, activePeriod)}` : "");
  const crossDateLabel = hasCross ? dateLabel(grouped.cross[0].date) : "";
  const srTouchDateLabel = hasSrTouch ? dateLabel(grouped.srTouch[0].date) : "";
  const volumeSpikeDateLabel = hasVolumeSpike ? dateLabel(grouped.volumeSpike[0].date) : "";
  const patternDateLabel = hasPattern ? dateLabel(cupHandles[0].bottomDate) : "";

  // 가격 시리즈: x키 = 유일한 전체 날짜. MA 오버레이만 백엔드 overlays 에서 병합(신호 재계산 안 함).
  const priceData = useMemo<PricePoint[]>(() => {
    if (!activeData) return [];
    const rawCandles: RawCandle[] = activeData.candles || [];

    const movingAverageMaps = new Map<number, Map<string, number>>();
    const maOverlays = activeData.overlays?.moving_average;
    if (Array.isArray(maOverlays)) {
      for (const overlay of maOverlays) {
        movingAverageMaps.set(
          overlay.window,
          new Map(overlay.points.map((point) => [point.date, point.value]))
        );
      }
    }

    const points = rawCandles.map((candle) => {
      const dateStr = candleDate(candle);
      const point: PricePoint = {
        date: dateStr,
        close: candle.close,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        volume: candle.volume,
      };
      for (const [window, values] of movingAverageMaps.entries()) {
        point[`ma_${window}`] = values.get(dateStr) ?? null;
      }
      return point;
    });

    // cup_handle 컵 곡선 — 1y/5y 에서 패턴 토글 켰을 때만. **실제 3점(좌림·바닥·우림)만** 찍고
    // 나머지는 null(connectNulls + monotone 보간)로 잇는다. 파라볼라 3점 피팅은 좌우 팔 비대칭 시
    // vertex(최소)가 실제 바닥과 다른 곳으로 밀려 "틀린 곳에 파이는" 문제가 있어 쓰지 않는다.
    if (showPatternArea && patternRenderable) {
      for (const cup of cupHandles) {
        const idxLeft = findClosestDateIndex(cup.leftRimDate, points);
        const idxBottom = findClosestDateIndex(cup.bottomDate, points);
        const idxRight = findClosestDateIndex(cup.rightRimDate, points);
        if (idxLeft === -1 || idxBottom === -1 || idxRight === -1) continue;
        if (!(idxLeft < idxBottom && idxBottom < idxRight)) continue;
        points[idxLeft].cup_curve = cup.leftRimPrice ?? points[idxLeft].close;
        points[idxBottom].cup_curve = cup.bottomPrice ?? points[idxBottom].close;
        points[idxRight].cup_curve = cup.rightRimPrice ?? points[idxRight].close;
      }
    }

    return points;
  }, [activeData, showPatternArea, patternRenderable, cupHandles]);

  // Part B: 최고/최저 — candles 로 계산(전 기간 공통, 백엔드 annotation 없음).
  const highLow = useMemo(() => {
    if (!activeData?.candles) return null;
    return computeHighLow(activeData.candles);
  }, [activeData]);

  // ReferenceDot 가장자리 클리핑 방지용 padded Y domain.
  const yDomain = useMemo<[number | string, number | string]>(() => {
    if (priceData.length === 0) return ["auto", "auto"];
    let maxVal = -Infinity;
    let minVal = Infinity;
    for (const p of priceData) {
      const h = p.high ?? p.close;
      const l = p.low ?? p.close;
      if (h > maxVal) maxVal = h;
      if (l < minVal) minVal = l;
    }
    // S/R 레벨 마커가 캔들 밖(터치 tolerance)일 수 있으니 레벨값도 domain 에 포함해 안 잘리게.
    for (const s of srMarkers) {
      if (s.y > maxVal) maxVal = s.y;
      if (s.y < minVal) minVal = s.y;
    }
    const range = maxVal - minVal;
    const padding = range * 0.08 || 1000;
    return [Math.max(0, minVal - padding), maxVal + padding];
  }, [priceData, srMarkers]);

  // RSI 서브차트 시리즈 — x키 = 전체 날짜(annotation 정렬을 위해 통일). 분봉은 rsi 배열이 top-level.
  const rsiData = useMemo(() => {
    if (!activeData) return [] as Array<{ date: string; value: number }>;
    const rsiPoints: RsiPoint[] = activeData.subcharts?.rsi?.points || activeData.rsi || [];
    return rsiPoints.map((point) => ({
      date: point.date ?? point.timestamp ?? "",
      value: point.value,
    }));
  }, [activeData]);

  const rsiThresholds = useMemo(() => {
    const rsi = activeData?.subcharts?.rsi;
    return { overbought: rsi?.overbought ?? 70, oversold: rsi?.oversold ?? 30 };
  }, [activeData]);

  // 거래량 시리즈 — 백엔드 subcharts.volume.bars(is_spike 포함) 우선, 없으면 candles 폴백.
  const volumeData = useMemo(() => {
    const bars = activeData?.subcharts?.volume?.bars;
    if (Array.isArray(bars) && bars.length > 0) {
      return bars.map((b) => ({
        date: b.date ?? b.timestamp ?? "",
        volume: b.volume,
        isSpike: Boolean(b.is_spike),
      }));
    }
    return priceData.map((p) => ({ date: p.date, volume: p.volume, isSpike: false }));
  }, [activeData, priceData]);

  // 지지/저항 수평선 오버레이(레벨 라인). 분봉엔 overlays 없음 → [].
  const srLines = useMemo<SrLine[]>(() => {
    if (!showSr || !activeData?.overlays) return [];
    return activeData.overlays.support_resistance || [];
  }, [showSr, activeData]);

  // 핸들 구간 밴드(1y/5y) — geometry 로 음영.
  const handleBands = useMemo(() => {
    if (!showPatternArea || !patternRenderable || priceData.length === 0) return [];
    return cupHandles
      .map((cup) => {
        const start = priceData[findClosestDateIndex(cup.handleStartDate, priceData)]?.date;
        const end = priceData[findClosestDateIndex(cup.handleEndDate, priceData)]?.date;
        return { x1: start, x2: end, label: cup.label, cup };
      })
      .filter((b) => b.x1 && b.x2);
  }, [showPatternArea, patternRenderable, priceData, cupHandles]);

  // 컵 구간 밴드(좌림→우림) + 바닥 앵커 — geometry 좌표를 그대로 써서 "정확히 그 구간"을 표시.
  const cupRegions = useMemo(() => {
    if (!showPatternArea || !patternRenderable || priceData.length === 0) return [];
    return cupHandles
      .map((cup) => {
        const x1 = priceData[findClosestDateIndex(cup.leftRimDate, priceData)]?.date;
        const x2 = priceData[findClosestDateIndex(cup.rightRimDate, priceData)]?.date;
        const bottomIdx = findClosestDateIndex(cup.bottomDate, priceData);
        const bottomDate = priceData[bottomIdx]?.date;
        const bottomY = cup.bottomPrice ?? priceData[bottomIdx]?.close;
        return { key: cup.key, x1, x2, bottomDate, bottomY };
      })
      .filter((b) => b.x1 && b.x2);
  }, [showPatternArea, patternRenderable, priceData, cupHandles]);

  const axisTick = (val: string) => formatChartDate(val, activePeriod);

  return (
    <section
      id="a-chart"
      className="scroll-mt-16 border border-[#f1f5f9] rounded-2xl p-6 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_1px_3px_rgba(15,23,42,0.06)] bg-white"
    >
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <h2 className="flex items-center gap-2.5 text-base font-bold text-[#0f172a] m-0">
          <Info className="w-[19px] h-[19px] text-[#334155]" /> 가격 차트 · 기술 지표
        </h2>
        {/* Period toggles */}
        <div className="flex items-center gap-1 bg-[#f1f5f9] rounded-xl p-1">
          {periods.map((period) => (
            <button
              key={period}
              type="button"
              onClick={() => setActivePeriod(period)}
              className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-colors ${
                activePeriod === period
                  ? "bg-white text-[#4f46e5] shadow-sm"
                  : "text-[#64748b] hover:text-[#0f172a]"
              }`}
            >
              {PERIOD_MAP[period] ?? period}
            </button>
          ))}
        </div>
      </div>

      {!activeChart || !activeData ? (
        <div className="rounded-xl border border-dashed border-slate-200 bg-[#f8fafc] py-14 text-center text-sm text-slate-400">
          렌더 가능한 차트 데이터가 없습니다.
        </div>
      ) : (
        <div className="space-y-4">
          <div className="border border-[#f1f5f9] rounded-xl p-4.5">
            {/* Layer Toggles Line 1 */}
            <div className="flex items-center justify-between flex-wrap gap-2.5 pb-3 border-b border-[#f8fafc] mb-3">
              <div className="flex items-center gap-1.5 flex-wrap">
                <button
                  onClick={() => setShowMa(!showMa)}
                  className={`px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors ${
                    showMa ? "bg-indigo-50 text-[#4f46e5]" : "bg-slate-50 text-slate-400"
                  }`}
                >
                  이동평균 (MA)
                </button>
                <button
                  onClick={() => setShowSr(!showSr)}
                  className={`px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors ${
                    showSr ? "bg-indigo-50 text-[#4f46e5]" : "bg-slate-50 text-slate-400"
                  }`}
                >
                  지지저항
                </button>
                <div className="w-[1px] h-4 bg-slate-200 mx-1.5" />
                <button
                  onClick={() => setShowRsi(!showRsi)}
                  className={`px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors ${
                    showRsi ? "bg-indigo-50 text-[#4f46e5]" : "bg-slate-50 text-slate-400"
                  }`}
                >
                  RSI Panel
                </button>
                <button
                  onClick={() => setShowVolume(!showVolume)}
                  className={`px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors ${
                    showVolume ? "bg-indigo-50 text-[#4f46e5]" : "bg-slate-50 text-slate-400"
                  }`}
                >
                  Volume Panel
                </button>
              </div>
              <span className="text-[11px] text-[#cbd5e1] flex items-center gap-1">
                <MousePointerClick className="w-3 h-3" /> 클릭해 켜고 끄기
              </span>
            </div>

            {/* Derived Candle Unit Badge Display */}
            <div className="flex items-center justify-between flex-wrap gap-2.5 pb-3 border-b border-[#f8fafc] mb-3">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-[#94a3b8]">
                <span>캔들 단위</span>
                <span className="px-2.5 py-1 text-xs font-bold bg-[#f1f5f9] text-[#334155] rounded-lg border border-slate-200">
                  {candleUnitLabel}
                </span>
              </div>
              <span className="text-[11px] text-[#94a3b8] flex items-center gap-1">
                <Info className="w-3 h-3 text-[#94a3b8]" /> 신호·게이지는{" "}
                <b className="font-semibold text-[#64748b]">일봉 기준</b> 계산
              </span>
            </div>

            {/* Signal overlays Line 3 */}
            <div className="flex items-center justify-between flex-wrap gap-2.5 mb-2">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-[11px] font-semibold text-[#94a3b8] flex items-center gap-1 mr-1">
                  <GitCommitHorizontal className="w-3 h-3" /> 지표 신호
                </span>
                <button
                  onClick={() => hasCross && setShowGoldenCross(!showGoldenCross)}
                  disabled={!hasCross}
                  className={`px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors ${
                    !hasCross
                      ? "bg-slate-50 text-slate-300 border border-slate-100 cursor-not-allowed opacity-60"
                      : showGoldenCross
                        ? "bg-[#eef2ff] text-[#4f46e5] border border-indigo-200"
                        : "bg-[#f8fafc] text-slate-500 border border-slate-100"
                  }`}
                >
                  이동평균 골든/데드크로스{hasCross ? crossDateLabel : " (없음)"}
                </button>
                <button
                  onClick={() => hasSrTouch && setShowSrTouch(!showSrTouch)}
                  disabled={!hasSrTouch}
                  className={`px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors ${
                    !hasSrTouch
                      ? "bg-slate-50 text-slate-300 border border-slate-100 cursor-not-allowed opacity-60"
                      : showSrTouch
                        ? "bg-[#eef2ff] text-[#4f46e5] border border-indigo-200"
                        : "bg-[#f8fafc] text-slate-500 border border-slate-100"
                  }`}
                >
                  지지·저항 터치{hasSrTouch ? srTouchDateLabel : " (없음)"}
                </button>
                <button
                  onClick={() => hasVolumeSpike && setShowVolumeSpike(!showVolumeSpike)}
                  disabled={!hasVolumeSpike}
                  className={`px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors ${
                    !hasVolumeSpike
                      ? "bg-slate-50 text-slate-300 border border-slate-100 cursor-not-allowed opacity-60"
                      : showVolumeSpike
                        ? "bg-[#eef2ff] text-[#4f46e5] border border-indigo-200"
                        : "bg-[#f8fafc] text-slate-500 border border-slate-100"
                  }`}
                >
                  거래량 급증{hasVolumeSpike ? volumeSpikeDateLabel : " (없음)"}
                </button>
                <button
                  onClick={() => patternRenderable && setShowPatternArea(!showPatternArea)}
                  disabled={!patternRenderable}
                  className={`px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors ${
                    !patternRenderable
                      ? "bg-slate-50 text-slate-300 border border-slate-100 cursor-not-allowed opacity-60"
                      : showPatternArea
                        ? "bg-[#eef2ff] text-[#4f46e5] border border-indigo-200"
                        : "bg-[#f8fafc] text-slate-500 border border-slate-100"
                  }`}
                >
                  패턴 구간{patternRenderable ? patternDateLabel : " (없음)"}
                </button>
              </div>
              <span className="text-[11px] text-[#cbd5e1] flex items-center gap-1">
                <History className="w-3 h-3" /> 하나씩 켜 보기 권장
              </span>
            </div>

            {/* Pattern description details banner (cup_handle geometry) */}
            {showPatternArea &&
              patternRenderable &&
              cupHandles.map((cup) => {
                const stageLabel =
                  cup.candidateStage === "handle_forming"
                    ? "핸들 형성 중"
                    : cup.candidateStage === "cup_forming"
                      ? "컵 형성 중"
                      : cup.candidateStage === "confirmed"
                        ? "형성 완료"
                        : cup.candidateStage || "후보";
                return (
                  <div
                    key={cup.key}
                    className="mt-3.5 p-3.5 bg-indigo-50/40 border border-indigo-100 rounded-xl flex items-center justify-between text-xs flex-wrap gap-2 animate-fade-in"
                  >
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-[#4f46e5]">{cup.label}</span>
                      <span className="bg-indigo-100/70 text-[#4f46e5] px-2 py-0.5 rounded font-semibold">
                        {stageLabel}
                      </span>
                      <span className="text-slate-500 font-medium">
                        깊이 {Math.round((cup.cupDepthPct || 0) * 100)}% · 눌림{" "}
                        {Math.round((cup.handlePullbackPct || 0) * 100)}%
                      </span>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded font-bold ${
                        cup.volumeConfirmed
                          ? "bg-emerald-50 text-emerald-700 border border-emerald-100"
                          : "bg-amber-50 text-amber-700 border border-amber-100"
                      }`}
                    >
                      {cup.volumeConfirmed ? "거래량 확인" : "거래량 미확인"}
                    </span>
                  </div>
                );
              })}

            {/* Main Price Chart */}
            <div className="h-[288px] relative mt-4">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={priceData}>
                  <defs>
                    <linearGradient id="priceGradient" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="#4f46e5" stopOpacity={0.16} />
                      <stop offset="100%" stopColor="#4f46e5" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#f1f5f9" strokeWidth={1} vertical={false} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={axisTick}
                    tick={{ fill: "#94a3b8", fontSize: 11 }}
                    minTickGap={24}
                  />
                  <YAxis
                    tick={{ fill: "#94a3b8", fontSize: 11 }}
                    width={58}
                    domain={yDomain}
                    tickFormatter={(val: number) => val.toLocaleString("ko-KR")}
                  />
                  <Tooltip
                    contentStyle={{ borderRadius: 12, borderColor: "#e2e8f0" }}
                    labelFormatter={(val) => formatChartDate(String(val), activePeriod)}
                    formatter={(val) => (typeof val === "number" ? val.toLocaleString("ko-KR") : val)}
                  />

                  {/* Cup region band (좌림→우림) — 컵 전체 구간을 정확히 음영 */}
                  {showPatternArea &&
                    cupRegions.map((region) => (
                      <ReferenceArea
                        key={`cup-${region.key}`}
                        x1={region.x1}
                        x2={region.x2}
                        fill="rgba(99, 102, 241, 0.06)"
                        stroke="#6366f1"
                        strokeOpacity={0.35}
                        strokeDasharray="2 4"
                        strokeWidth={1}
                        label={{
                          value: "컵 구간",
                          fill: "#6366f1",
                          fontSize: 10,
                          position: "insideTopLeft",
                        }}
                      />
                    ))}

                  {/* Handle Bands (cup_handle) */}
                  {showPatternArea &&
                    handleBands.map((band, index) => (
                      <ReferenceArea
                        key={`handle-${index}`}
                        x1={band.x1}
                        x2={band.x2}
                        fill="rgba(249, 115, 22, 0.08)"
                        stroke="#f97316"
                        strokeDasharray="3 3"
                        strokeWidth={1}
                        label={{
                          value: `${band.label} (${Math.round((band.cup.handlePullbackPct || 0) * 100)}% 눌림)`,
                          fill: "#ea580c",
                          fontSize: 10,
                          position: "insideTopRight",
                        }}
                      />
                    ))}

                  {/* Base Close Price Area */}
                  <Area
                    type="monotone"
                    dataKey="close"
                    stroke="#4f46e5"
                    strokeWidth={2}
                    fill="url(#priceGradient)"
                    name="종가"
                    isAnimationActive={false}
                  />

                  {/* Cup curve — 실제 3점(좌림·바닥·우림)만 지나는 U자(바닥이 정확히 bottom_date) */}
                  {showPatternArea && (
                    <Area
                      type="monotone"
                      dataKey="cup_curve"
                      stroke="#6366f1"
                      strokeWidth={2.2}
                      strokeDasharray="4 4"
                      fill="none"
                      dot={false}
                      activeDot={false}
                      connectNulls
                      name="컵 곡선"
                      isAnimationActive={false}
                    />
                  )}

                  {/* Cup 바닥 앵커 마커(정확히 bottom_date/price) */}
                  {showPatternArea &&
                    cupRegions.map((region) =>
                      region.bottomDate && region.bottomY != null ? (
                        <ReferenceDot
                          key={`cupbottom-${region.key}`}
                          x={region.bottomDate}
                          y={region.bottomY}
                          r={4}
                          fill="#6366f1"
                          stroke="#fff"
                          strokeWidth={1.5}
                          label={{
                            value: `컵 바닥 ${formatNumber(region.bottomY)}`,
                            fill: "#4f46e5",
                            fontSize: 9.5,
                            position: "bottom",
                            fontWeight: "bold",
                          }}
                        />
                      ) : null
                    )}

                  {/* MA Overlays */}
                  {showMa && (
                    <>
                      <Line type="monotone" dataKey="ma_5" stroke="#f59e0b" dot={false} strokeWidth={1.8} name="5 MA" isAnimationActive={false} />
                      <Line type="monotone" dataKey="ma_20" stroke="#8b5cf6" dot={false} strokeWidth={1.8} name="20 MA" isAnimationActive={false} />
                      <Line type="monotone" dataKey="ma_60" stroke="#475569" dot={false} strokeWidth={1.8} name="60 MA" isAnimationActive={false} />
                    </>
                  )}

                  {/* S/R Reference Lines (level 라인) */}
                  {srLines.map((line, index) => (
                    <ReferenceLine
                      key={`${line.type}-${index}`}
                      y={line.price}
                      stroke={line.type === "support" ? "#10b981" : "#f43f5e"}
                      strokeDasharray="6 4"
                      strokeWidth={1.2}
                      label={{
                        value: line.type === "support" ? "지지" : "저항",
                        fill: "#94a3b8",
                        fontSize: 10,
                        position: "insideBottomLeft",
                      }}
                    />
                  ))}

                  {/* Part B: 최고/최저 마커 (candles 계산) */}
                  {highLow?.highest && (
                    <ReferenceDot
                      x={highLow.highest.date}
                      y={highLow.highest.value}
                      r={4}
                      fill="#f43f5e"
                      stroke="#fff"
                      strokeWidth={1.5}
                      label={{
                        value: `최고 ${formatNumber(highLow.highest.value)} (${formatChartDate(highLow.highest.date, activePeriod)})`,
                        fill: "#f43f5e",
                        fontSize: 9.5,
                        position: "top",
                        fontWeight: "bold",
                      }}
                    />
                  )}
                  {highLow?.lowest && (
                    <ReferenceDot
                      x={highLow.lowest.date}
                      y={highLow.lowest.value}
                      r={4}
                      fill="#10b981"
                      stroke="#fff"
                      strokeWidth={1.5}
                      label={{
                        value: `최저 ${formatNumber(highLow.lowest.value)} (${formatChartDate(highLow.lowest.date, activePeriod)})`,
                        fill: "#10b981",
                        fontSize: 9.5,
                        position: "bottom",
                        fontWeight: "bold",
                      }}
                    />
                  )}

                  {/* Part A: Golden/Dead Cross dots (price = 종가 → 종가선 위) */}
                  {showGoldenCross &&
                    crossMarkers.map((ann) => {
                      const isGolden = ann.kind === "golden_cross";
                      return (
                        <ReferenceDot
                          key={`cross-${ann.key}`}
                          x={ann.date}
                          y={ann.y}
                          r={5}
                          fill={isGolden ? "#10b981" : "#f43f5e"}
                          stroke="#fff"
                          strokeWidth={1.5}
                          label={{
                            value: `${ann.label} (${formatChartDate(ann.date, activePeriod)})`,
                            fill: isGolden ? "#10b981" : "#f43f5e",
                            fontSize: 9.5,
                            position: "top",
                            fontWeight: "bold",
                          }}
                        />
                      );
                    })}

                  {/* Part A: Volume Spike dots (price = 종가) */}
                  {showVolumeSpike &&
                    volumeSpikeMarkers.map((ann) => (
                      <ReferenceDot
                        key={`vol-${ann.key}`}
                        x={ann.date}
                        y={ann.y}
                        r={5}
                        fill="#f97316"
                        stroke="#fff"
                        strokeWidth={1.5}
                        label={{
                          value: `${ann.label} (${formatChartDate(ann.date, activePeriod)})`,
                          fill: "#ea580c",
                          fontSize: 9.5,
                          position: "top",
                          fontWeight: "bold",
                        }}
                      />
                    ))}

                  {/* Part A: S/R 터치 = 레벨 마커(price=레벨값, 종가선에 스냅하지 않음) */}
                  {showSrTouch &&
                    srMarkers.map((ann) => {
                      const isSupport = ann.side === "support";
                      // 레벨 마커: 지지/저항 레벨값(ann.y) 위에 찍는다(종가선 스냅 아님). 색으로 방향 구분.
                      return (
                        <ReferenceDot
                          key={`sr-${ann.key}`}
                          x={ann.date}
                          y={ann.y}
                          r={4}
                          fill={isSupport ? "#10b981" : "#f43f5e"}
                          stroke="#fff"
                          strokeWidth={1.5}
                          label={{
                            value: `${ann.label} (${formatChartDate(ann.date, activePeriod)})`,
                            fill: isSupport ? "#059669" : "#e11d48",
                            fontSize: 9.5,
                            position: isSupport ? "bottom" : "top",
                            fontWeight: "bold",
                          }}
                        />
                      );
                    })}
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            {/* Subchart: RSI (14) — rsi_overbought/oversold annotation 은 여기서만 렌더 */}
            {showRsi && (
              <div className="mt-4 pt-4 border-t border-[#f8fafc]">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-bold text-[#64748b]">RSI (14)</span>
                  <span className="text-xs font-bold font-tabular text-[#d97706]">
                    {rsiData[rsiData.length - 1]?.value?.toFixed(1) ?? "—"}
                  </span>
                </div>
                <div className="h-[92px] relative">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={rsiData}>
                      <CartesianGrid stroke="#f8fafc" strokeWidth={1} vertical={false} />
                      <XAxis dataKey="date" hide />
                      <YAxis domain={[0, 100]} width={30} tick={{ fill: "#94a3b8", fontSize: 10 }} />
                      <Tooltip
                        labelFormatter={(val) => formatChartDate(String(val), activePeriod)}
                      />
                      <ReferenceLine y={rsiThresholds.overbought} stroke="#f59e0b" strokeDasharray="4 4" strokeWidth={1} />
                      <ReferenceLine y={rsiThresholds.oversold} stroke="#10b981" strokeDasharray="4 4" strokeWidth={1} />
                      <Area
                        type="monotone"
                        dataKey="value"
                        stroke="#f59e0b"
                        fill="rgba(245, 158, 11, 0.05)"
                        strokeWidth={1.8}
                        isAnimationActive={false}
                      />
                      {/* RSI 과매수/과매도 마커 — 가격 차트가 아니라 여기(RSI panel)에만 */}
                      {rsiAnnotations.map((ann) => {
                        const isOver = ann.kind === "rsi_overbought";
                        return (
                          <ReferenceDot
                            key={`rsi-${ann.key}`}
                            x={ann.date}
                            y={ann.rsi}
                            r={3.5}
                            fill={isOver ? "#f43f5e" : "#10b981"}
                            stroke="#fff"
                            strokeWidth={1.2}
                          />
                        );
                      })}
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* Subchart: Volume — is_spike 는 백엔드 subcharts.volume.bars 값 */}
            {showVolume && (
              <div className="mt-4 pt-4 border-t border-[#f8fafc]">
                <div className="text-xs font-bold text-[#64748b] mb-1.5">거래량</div>
                <div className="h-[80px] relative">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={volumeData}>
                      <CartesianGrid stroke="#f8fafc" strokeWidth={1} vertical={false} />
                      <XAxis dataKey="date" hide />
                      <YAxis
                        width={30}
                        tick={{ fill: "#94a3b8", fontSize: 10 }}
                        tickFormatter={(val: number) => {
                          if (val >= 1000000) return `${(val / 1000000).toFixed(0)}M`;
                          return val.toString();
                        }}
                      />
                      <Tooltip labelFormatter={(val) => formatChartDate(String(val), activePeriod)} />
                      <Bar dataKey="volume" radius={[2, 2, 0, 0]} isAnimationActive={false}>
                        {volumeData.map((d) => (
                          <Cell
                            key={`vbar-${d.date}`}
                            fill={showVolumeSpike && d.isSpike ? "#fb7185" : "#cbd5e1"}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* Info Footer Label */}
            <div className="flex items-center gap-1.5 mt-4 text-[12px] text-[#94a3b8]">
              <Info className="w-3.5 h-3.5" />
              <span>
                출처: KIS 시세 · {isIntraday ? "실시간 분봉" : `${candleUnitLabel} 기준`}
              </span>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
