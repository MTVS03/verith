/**
 * Technical Report 계약 — POST/GET /api/technical/reports
 * 정본: backend/src/api/schemas/technical_report.py
 *
 * 조회 계약 = read model(프론트 친화, 섹션별 바로 렌더). 모든 값은 저장/계산값의 projection 이며
 * backend 는 재해석하지 않는다. optional 필드가 비어도 shape 는 안정적이다.
 */

// ── 요청 ──────────────────────────────────────────────────────────────────
export interface TechnicalReportCreateRequest {
  ticker: string; // 6자리 종목코드(앞자리 0 보존) — /^\d{6}$/
  query: string; // 1자 이상
  client_session_id?: string | null;
  stock_name?: string | null;
  as_of?: string | null; // ISO datetime
}

// ── read model 블록 ──────────────────────────────────────────────────────
export interface StockBlock {
  stock_code: string;
  stock_name: string | null;
  market: string | null;
}

export interface MetaBlock {
  request_id: string | null;
  trace_id: string | null;
  as_of: string | null;
  source: string | null;
  data_status: string | null;
  model_name: string | null;
}

export interface SummaryBlock {
  one_line_summary: string | null;
  directional_bias: string | null; // bullish/neutral/bearish
  final_regime: string | null;
  daily_regime: string | null;
  weekly_trend: string | null;
  monthly_trend: string | null;
  alignment_flag: string | null;
  timeframe_alignment: string | null;
}

export interface InterpretationBlock {
  text: string | null;
  source: string | null;
  trend_interpretation: string | null;
  signal_interpretation: string | null;
  risk_interpretation: string | null;
  what_to_watch_next: string | null;
  invalidation_or_caution: string | null;
}

export interface DriversBlock {
  key_drivers: string[];
  warning_points: string[];
}

export interface SignalItem {
  indicator: string;
  signal: string | null;
  value: number | null;
  metrics: string[];
  detail: string | null;
  detail_source: string | null;
}

export interface SignalsBlock {
  signal_score: number | null;
  consensus: string | null;
  confidence: number | null;
  confidence_basis: string | null;
  items: SignalItem[];
}

export interface RiskItemBlock {
  flag: string;
  note: string | null;
  ref_price: number | null;
}

export interface RisksBlock {
  items: RiskItemBlock[];
}

export interface ChartItem {
  period: string;
  candle_unit: string | null;
  display_order: number;
  has_chart_data: boolean;
  annotation_count: number;
}

export interface ChartsBlock {
  available_periods: string[];
  items: ChartItem[];
}

export interface DataQualityBlock {
  data_status: string | null;
  available_periods: string[];
  intraday_available: boolean;
  chart_count: number;
  limited: boolean;
}

export interface SignalQualityBlock {
  signal_score: number | null;
  signal_label: string | null;
  consensus: string | null;
  confidence: number | null;
  confidence_basis: string | null;
}

export interface VerificationGateBlock {
  outcome: string | null;
  calc_passed: boolean | null;
  regime_passed: boolean | null;
  label_matched: boolean | null;
  verification_warning: boolean;
}

export interface SourceLinkageBlock {
  total_signal_items: number;
  sourced_signal_items: number;
  source_coverage_ratio: number;
}

export interface TrustSummaryBlock {
  signal_quality: SignalQualityBlock;
  data_quality: DataQualityBlock;
  verification_gate: VerificationGateBlock;
  source_linkage: SourceLinkageBlock;
}

export interface GenerationPathBlock {
  source: string | null;
  interpretation_source: string | null;
  template_fallback_used: boolean;
  regen_count: number | null;
  path_label: string;
}

export interface StabilityBlock {
  confidence: number | null;
  confidence_basis: string | null;
  verification_consistent: boolean | null;
}

export interface TraceSummaryBlock {
  trace_id: string | null;
  generation_path: GenerationPathBlock;
  data_quality: DataQualityBlock;
  verification_summary: {
    outcome: string | null;
    calc_passed: boolean | null;
    regime_passed: boolean | null;
    label_matched: boolean | null;
    failed_indicators_count: number;
  };
  stability: StabilityBlock;
  flags: Record<string, boolean>;
}

/**
 * POST/GET 단건 응답. trace_summary 등 일부 블록은 상세 화면(Phase 4)에서 쓰므로
 * 여기서는 Research 결과 카드에 필요한 최소 블록 위주로 타입을 노출한다(unknown 으로 보존).
 */
export interface TechnicalReportReadModel {
  report_id: string;
  stock: StockBlock;
  meta: MetaBlock;
  summary: SummaryBlock;
  interpretation: InterpretationBlock;
  drivers: DriversBlock;
  signals: SignalsBlock;
  risks: RisksBlock;
  charts: ChartsBlock;
  verification: unknown;
  trace_summary: TraceSummaryBlock;
  trust_summary: TrustSummaryBlock;
  followup_count: number;
}
