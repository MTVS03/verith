export type StockBlock = {
  stock_code: string;
  stock_name: string | null;
  market: string | null;
};

export type TechnicalReportListItem = {
  report_id: string;
  stock: StockBlock;
  summary: {
    one_line_summary: string | null;
    directional_bias: "bullish" | "neutral" | "bearish" | null;
    final_regime: string | null;
  };
  status: {
    data_status: string | null;
    path_label: "normal" | "regenerated" | "template_fallback";
    verification_warning: boolean;
    limited_data: boolean;
  };
  engagement: {
    followup_count: number;
  };
  meta: {
    as_of: string | null;
    created_at: string | null;
    trace_id: string | null;
  };
};

export type TechnicalReportListResponse = {
  items: TechnicalReportListItem[];
  total: number;
  limit: number;
  offset: number;
};

export type TechnicalReportReadModel = {
  report_id: string;
  stock: StockBlock;
  meta: {
    request_id: string | null;
    trace_id: string | null;
    as_of: string | null;
    source: string | null;
    data_status: string | null;
    model_name: string | null;
  };
  summary: {
    one_line_summary: string | null;
    directional_bias: "bullish" | "neutral" | "bearish" | null;
    final_regime: string | null;
    daily_regime: string | null;
    weekly_trend: string | null;
    monthly_trend: string | null;
    alignment_flag: string | null;
    timeframe_alignment: string | null;
  };
  interpretation: {
    text: string | null;
    source: "llm" | "llm_regenerated" | "template_fallback" | null;
    trend_interpretation: string | null;
    signal_interpretation: string | null;
    risk_interpretation: string | null;
    what_to_watch_next: string | null;
    invalidation_or_caution: string | null;
  };
  drivers: {
    key_drivers: string[];
    warning_points: string[];
  };
  signals: {
    signal_score: number | null;
    consensus: string | null;
    confidence: number | null;
    confidence_basis: string | null;
    items: Array<{
      indicator: string;
      signal: string | null;
      value: number | null;
      metrics: string[];
      detail: string | null;
      detail_source: string | null;
    }>;
  };
  risks: {
    items: Array<{
      flag: string;
      note: string | null;
      ref_price: number | null;
    }>;
  };
  charts: {
    available_periods: string[];
    items: Array<{
      period: string;
      candle_unit: string | null;
      display_order: number;
      has_chart_data: boolean;
      annotation_count: number;
    }>;
  };
  verification: {
    outcome: string | null;
    calc_passed: boolean | null;
    regime_passed: boolean | null;
    label_matched: boolean | null;
    regen_count: number | null;
    failed_indicators: string[];
    summary: string | null;
  };
  trace_summary: {
    trace_id: string | null;
    generation_path: {
      source: string | null;
      interpretation_source: string | null;
      template_fallback_used: boolean;
      regen_count: number | null;
      path_label: "normal" | "regenerated" | "template_fallback";
    };
    data_quality: {
      data_status: string | null;
      available_periods: string[];
      intraday_available: boolean;
      chart_count: number;
      limited: boolean;
    };
    verification_summary: {
      outcome: string | null;
      calc_passed: boolean | null;
      regime_passed: boolean | null;
      label_matched: boolean | null;
      failed_indicators_count: number;
    };
    stability: {
      confidence: number | null;
      confidence_basis: string | null;
      verification_consistent: boolean | null;
    };
    flags: {
      used_fallback: boolean;
      had_regeneration: boolean;
      limited_data: boolean;
      verification_warning: boolean;
      has_intraday_context: boolean;
      has_daily_chart: boolean;
      has_weekly_chart: boolean;
      has_monthly_chart: boolean;
    };
  };
  trust_summary: {
    signal_quality: {
      signal_score: number | null;
      signal_label: string | null;
      consensus: string | null;
      confidence: number | null;
      confidence_basis: string | null;
    };
    data_quality: {
      data_status: string | null;
      available_periods: string[];
      intraday_available: boolean;
      chart_count: number;
      limited: boolean;
    };
    verification_gate: {
      outcome: string | null;
      calc_passed: boolean | null;
      regime_passed: boolean | null;
      label_matched: boolean | null;
      verification_warning: boolean;
    };
    source_linkage: {
      total_signal_items: number;
      sourced_signal_items: number;
      source_coverage_ratio: number;
    };
  };
  indicator_cards?: IndicatorCard[];
  followup_count: number;
};

export type AnnotationBrief = {
  kind: string;
  label: string | null;
  period: string | null;
  date: string | null;
  importance: string | null;
  meta: Record<string, any> | null;
};

export type IndicatorCalcBasis = {
  kind: string;
  current_value: number | null;
  ma: Record<string, number> | null;
  alignment: string | null;
  rsi_period: number | null;
  oversold: number | null;
  overbought: number | null;
  relative_volume: number | null;
  support: number | null;
  resistance: number | null;
  position: string | null;
  disparity_20_pct: number | null;
  recent_ma: Array<Record<string, any>>;
  rsi_recent_points: Array<{ date: string; value: number }>;
  current_volume: number | null;
  avg_volume: number | null;
  volume_recent_bars: Array<{ date: string; volume: number }>;
  metrics: string[];
  related_annotations: AnnotationBrief[];
};

export type IndicatorCard = {
  indicator: string;
  title: string;
  signal: string | null;
  signal_label: string | null;
  weight: number | null;
  llm_detail: string | null;
  detail_source: string | null;
  detail_reason?: string | null;
  detail_caution?: string | null;
  detail_watchpoint?: string | null;
  verified: boolean;
  code_metrics: string[];
  calc_basis: IndicatorCalcBasis;
  pattern_candidates: AnnotationBrief[];
};

type DailyWeeklyMonthlyChartData = {
  candle_unit: "D" | "W" | "M";
  candles: Array<{
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    trading_value?: number | null;
  }>;
  overlays: {
    moving_average: Array<{
      window: number;
      points: Array<{ date: string; value: number }>;
    }>;
    support_resistance: Array<{
      type: "support" | "resistance";
      price: number;
      from: string;
      to: string;
      touch_count: number;
    }>;
  };
  subcharts: {
    rsi: {
      period: number;
      overbought: number;
      oversold: number;
      points: Array<{ date: string; value: number }>;
    };
    volume: {
      avg_window: number;
      bars: Array<{
        date: string;
        volume: number;
        avg_volume: number | null;
        is_spike: boolean;
      }>;
    };
  };
  annotations: Array<{
    id: string;
    kind: string;
    date: string;
    price: number | null;
    label: string;
    importance: "low" | "medium" | "high";
    source: "code";
    meta?: Record<string, unknown>;
  }>;
};

type IntradayChartData = {
  candle_unit: "1min";
  candles: Array<{
    timestamp: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    trading_value?: number | null;
    interval: "1min";
  }>;
  previous_close: number | null;
  day_high: number | null;
  day_low: number | null;
  short_ma: Array<{ timestamp: string; value: number }>;
  vwap: Array<{ timestamp: string; value: number }>;
  rsi: Array<{ timestamp: string; value: number }>;
};

export type TechnicalChartsReadModel = {
  report_id: string;
  stock: StockBlock;
  available_periods: string[];
  charts: Array<{
    period: string;
    candle_unit: string | null;
    display_order: number;
    has_chart_data: boolean;
    annotation_count: number;
    chart_data: DailyWeeklyMonthlyChartData | IntradayChartData | null;
    annotations: Array<Record<string, unknown>>;
  }>;
};

export type TechnicalTraceDetailReadModel = {
  report_id: string;
  overall: {
    total_steps: number;
    total_duration_ms: number | null;
    llm_used: boolean;
    data_source_summary: string | null;
  };
  steps: Array<{
    step_order: number;
    step_key: string;
    title: string;
    source: string | null;
    duration_ms: number | null;
    status: "ok" | "degraded" | "skipped" | "fallback";
    short_description: string | null;
    llm_involved: boolean;
  }>;
};

export type FollowupItem = {
  followup_id: string;
  request_id: string | null;
  question: string | null;
  answer: string | null;
  model_name: string | null;
  trace_id: string | null;
  created_at: string | null;
  answer_length: number;
  context: {
    has_context_snapshot: boolean;
    base_report_regime: string | null;
    base_report_bias: string | null;
    base_report_data_status: string | null;
    base_report_signal_score: number | null;
    base_report_as_of: string | null;
  };
};

export type TechnicalReportFollowupsReadModel = {
  report_id: string;
  stock: StockBlock;
  report_summary: {
    one_line_summary: string | null;
    directional_bias: "bullish" | "neutral" | "bearish" | null;
    final_regime: string | null;
    as_of: string | null;
  };
  followup_count: number;
  followups: FollowupItem[];
};
