// technical 상세 차트 annotation 좌표 규칙 헬퍼.
//
// 백엔드 chart_data.annotations 는 신호 종류별로 price 의미가 다르다 — 프론트가 전부 "종가 좌표"로
// 찍으면 S/R 터치가 틀린 곳에 보이고 RSI 신호가 가격 차트에 잘못 나온다. 이 모듈이 kind별 규칙을
// 한곳에서 분기한다(백엔드 데이터·price 의미는 그대로 신뢰, 변경하지 않는다).
//
//  - golden_cross / dead_cross / volume_spike : price = 해당 캔들 종가(close) → 가격선 위 점
//  - support_touch / resistance_touch         : price = 지지/저항 레벨값(종가 아님) → 레벨 마커
//  - rsi_overbought / rsi_oversold            : price=null, meta.rsi = RSI값 → RSI 서브차트 전용
//  - cup_handle_candidate                     : meta geometry 로 구간 하이라이트(annotation-only)

export type ChartAnnotation = {
  id?: string;
  kind: string;
  date: string;
  price: number | null;
  label?: string;
  importance?: "low" | "medium" | "high";
  source?: string;
  meta?: Record<string, unknown>;
};

export type PriceAnnotationRender = {
  key: string;
  kind: string;
  /** 가격선 위 점(cross·volume) vs 지지/저항 레벨 마커 */
  marker: "price" | "level";
  /** support/resistance 방향(level 마커에서 색·라벨 분기) */
  side?: "support" | "resistance";
  date: string;
  y: number;
  label: string;
};

export type RsiAnnotationRender = {
  key: string;
  kind: "rsi_overbought" | "rsi_oversold";
  date: string;
  /** RSI 서브차트 y좌표(0~100) — meta.rsi */
  rsi: number;
  label: string;
};

export type CupHandleGeometry = {
  key: string;
  label: string;
  importance?: string;
  leftRimDate?: string;
  bottomDate?: string;
  rightRimDate?: string;
  handleStartDate?: string;
  handleEndDate?: string;
  leftRimPrice?: number;
  bottomPrice?: number;
  rightRimPrice?: number;
  cupDepthPct?: number;
  handlePullbackPct?: number;
  volumeConfirmed?: boolean;
  candidateStage?: string;
};

const CROSS_KINDS = new Set(["golden_cross", "dead_cross"]);
const SR_KINDS = new Set(["support_touch", "resistance_touch"]);
const RSI_KINDS = new Set(["rsi_overbought", "rsi_oversold"]);
const PATTERN_KINDS = new Set([
  "cup_handle_candidate",
  "box_breakout_candidate",
  "box_range_candidate",
]);

/** 일봉/주봉/월봉은 date, 분봉(1d)은 timestamp — 캔들 x키를 통일해서 읽는다. */
export function candleDate(candle: Record<string, unknown>): string {
  return (candle.date as string) ?? (candle.timestamp as string) ?? "";
}

/** 원시 annotation 배열을 kind 그룹으로 나눈다(가격차트/RSI/패턴 렌더를 분리하기 위한 1차 분류). */
export function partitionAnnotationsByKind(annotations: ChartAnnotation[]) {
  const cross: ChartAnnotation[] = [];
  const volumeSpike: ChartAnnotation[] = [];
  const srTouch: ChartAnnotation[] = [];
  const rsi: ChartAnnotation[] = [];
  const pattern: ChartAnnotation[] = [];
  for (const a of annotations) {
    if (CROSS_KINDS.has(a.kind)) cross.push(a);
    else if (a.kind === "volume_spike") volumeSpike.push(a);
    else if (SR_KINDS.has(a.kind)) srTouch.push(a);
    else if (RSI_KINDS.has(a.kind)) rsi.push(a);
    else if (PATTERN_KINDS.has(a.kind)) pattern.push(a);
  }
  return { cross, volumeSpike, srTouch, rsi, pattern };
}

/**
 * 가격 차트에 찍을 annotation 렌더 목록.
 *  - cross/volume_spike: y = price(=종가) → 종가선 위 점(marker:"price")
 *  - support/resistance_touch: y = price(=레벨) → 레벨 마커(marker:"level"), 종가선에 스냅하지 않음
 * price 가 없으면(비정상/RSI 등) 제외한다.
 */
export function getPriceChartAnnotations(
  annotations: ChartAnnotation[]
): PriceAnnotationRender[] {
  const { cross, volumeSpike, srTouch } = partitionAnnotationsByKind(annotations);
  const out: PriceAnnotationRender[] = [];
  const push = (a: ChartAnnotation, marker: "price" | "level", i: number) => {
    if (a.price == null || !a.date) return;
    out.push({
      key: a.id ?? `${a.kind}-${a.date}-${i}`,
      kind: a.kind,
      marker,
      side:
        a.kind === "support_touch"
          ? "support"
          : a.kind === "resistance_touch"
            ? "resistance"
            : undefined,
      date: a.date,
      y: a.price,
      label: a.label ?? a.kind,
    });
  };
  cross.forEach((a, i) => push(a, "price", i));
  volumeSpike.forEach((a, i) => push(a, "price", i));
  srTouch.forEach((a, i) => push(a, "level", i));
  return out;
}

/** RSI 서브차트에 찍을 annotation(가격 메인 차트 아님). meta.rsi(0~100)를 y로 쓴다. */
export function getRsiAnnotations(annotations: ChartAnnotation[]): RsiAnnotationRender[] {
  const { rsi } = partitionAnnotationsByKind(annotations);
  const out: RsiAnnotationRender[] = [];
  rsi.forEach((a, i) => {
    const value = a.meta?.rsi;
    if (typeof value !== "number" || !a.date) return;
    out.push({
      key: a.id ?? `${a.kind}-${a.date}-${i}`,
      kind: a.kind as RsiAnnotationRender["kind"],
      date: a.date,
      rsi: value,
      label: a.label ?? a.kind,
    });
  });
  return out;
}

/** cup_handle 후보 geometry(1y/5y 구간 하이라이트용). annotation-only — 신호 점수에 반영하지 않는다. */
export function getCupHandleGeometry(annotations: ChartAnnotation[]): CupHandleGeometry[] {
  return annotations
    .filter((a) => a.kind === "cup_handle_candidate")
    .map((a, i) => {
      const m = a.meta ?? {};
      const num = (k: string) => (typeof m[k] === "number" ? (m[k] as number) : undefined);
      const str = (k: string) => (typeof m[k] === "string" ? (m[k] as string) : undefined);
      return {
        key: a.id ?? `cup-${a.date}-${i}`,
        label: a.label ?? "컵앤핸들 후보",
        importance: a.importance,
        leftRimDate: str("left_rim_date"),
        bottomDate: str("bottom_date"),
        rightRimDate: str("right_rim_date"),
        handleStartDate: str("handle_start_date"),
        handleEndDate: str("handle_end_date"),
        leftRimPrice: num("left_rim_price"),
        bottomPrice: num("bottom_price"),
        rightRimPrice: num("right_rim_price"),
        cupDepthPct: num("cup_depth_pct"),
        handlePullbackPct: num("handle_pullback_pct"),
        volumeConfirmed: typeof m.volume_confirmed === "boolean" ? (m.volume_confirmed as boolean) : undefined,
        candidateStage: str("candidate_stage"),
      };
    });
}

/**
 * 기간 최고/최저를 계산한다(백엔드 period_high/low annotation 없음 — 프론트 계산, 전 기간 공통).
 *
 * 표시 형태에 맞춘다: **봉차트(useWick=true)** 면 고가/저가(심지) 기준 → 마커가 실제 최고/최저 봉에
 * 앉는다. **종가선(useWick=false)** 이면 종가 기준 → 선의 peak/trough 위에 앉는다. (3m 처럼 고가최고와
 * 종가최고가 다른 날일 때, 형태에 안 맞추면 마커가 엉뚱한 봉에 찍혀 어긋나 보인다.)
 */
export function computeHighLow(candles: Array<Record<string, unknown>>, useWick = true) {
  if (!candles || candles.length === 0) return null;
  const hi = (c: Record<string, unknown>) =>
    useWick ? ((c.high as number) ?? (c.close as number)) : (c.close as number);
  const lo = (c: Record<string, unknown>) =>
    useWick ? ((c.low as number) ?? (c.close as number)) : (c.close as number);
  let highest = candles[0];
  let lowest = candles[0];
  for (const c of candles) {
    if (hi(c) > hi(highest)) highest = c;
    if (lo(c) < lo(lowest)) lowest = c;
  }
  return {
    highest: { date: candleDate(highest), value: hi(highest) },
    lowest: { date: candleDate(lowest), value: lo(lowest) },
  };
}

/** 축/라벨 표시용 날짜 포맷(x키는 항상 유일한 전체 날짜를 쓰고, 표시만 여기서 축약). */
export function formatChartDate(dateStr: string, period: string): string {
  if (!dateStr) return "";
  if (period === "1d") {
    // 분봉 timestamp "YYYY-MM-DDTHH:mm:ss" → HH:mm
    return dateStr.length >= 16 ? dateStr.slice(11, 16) : dateStr;
  }
  if (period === "5y") {
    // 5년 주봉은 연도가 반복되므로 YY.MM 로(같은 MM/DD 혼동 방지)
    return dateStr.length >= 7 ? `${dateStr.slice(2, 4)}.${dateStr.slice(5, 7)}` : dateStr;
  }
  return dateStr.length >= 10 ? dateStr.slice(5, 10).replace("-", "/") : dateStr;
}
