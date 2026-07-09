import type {
  TechnicalChartsReadModel,
  TechnicalReportFollowupsReadModel,
  TechnicalReportReadModel,
  TechnicalTraceDetailReadModel,
} from "@/types/technical";

export const demoTechnicalReport: TechnicalReportReadModel = {
  report_id: "demo-technical-report",
  stock: {
    stock_code: "373220",
    stock_name: "LG에너지솔루션",
    market: "KOSPI",
  },
  meta: {
    request_id: "demo-req-technical-001",
    trace_id: "demo-trace-technical-001",
    as_of: "2026-07-09T10:15:00+09:00",
    source: "KIS",
    data_status: "normal",
    model_name: "gpt-demo",
  },
  summary: {
    one_line_summary: "중장기 추세는 견조하지만 단기 과열 신호가 있어 눌림 확인이 중요한 구간입니다.",
    directional_bias: "bullish",
    final_regime: "uptrend_intact",
    daily_regime: "uptrend_intact",
    weekly_trend: "up",
    monthly_trend: "up",
    alignment_flag: "aligned",
    timeframe_alignment: "일·주·월 추세가 같은 방향으로 정렬되어 있습니다.",
  },
  interpretation: {
    text: "중장기 상승 흐름은 유지되고 있습니다. 다만 단기적으로는 과열 신호와 거래량 둔화가 함께 보여 추격 진입보다는 눌림 구간 확인이 더 중요합니다. 추세 자체는 살아 있으나 단기 진폭 확대 가능성은 열어둬야 합니다.",
    source: "llm",
    trend_interpretation: "월봉과 주봉 기준으로는 상승 추세 유지 쪽 해석이 더 강합니다.",
    signal_interpretation: "이동평균 배열과 추세 점수는 긍정적이지만, RSI는 단기 과열 영역에 근접해 있습니다.",
    risk_interpretation: "거래량이 강하게 동반되지 않으면 단기 피로 신호가 더 빨리 나타날 수 있습니다.",
    what_to_watch_next: "5일선 지지 여부와 거래량 재확인, 그리고 RSI 과열 해소 속도를 같이 볼 필요가 있습니다.",
    invalidation_or_caution: "단기 지지선 이탈과 함께 추세 점수가 빠르게 꺾이면 기존 상승 시나리오 신뢰도는 낮아집니다.",
  },
  drivers: {
    key_drivers: [
      "5·20·60 이동평균선 정배열 유지",
      "주봉·월봉 추세가 같은 방향으로 정렬",
      "중기 추세 점수는 양수권 유지",
    ],
    warning_points: [
      "단기 RSI 과열 구간 접근",
      "거래량 확인이 아직 강하지 않음",
      "추격 매수 시 단기 변동성 리스크 존재",
    ],
  },
  signals: {
    signal_score: 0.46,
    consensus: "weak_positive",
    confidence: 0.84,
    confidence_basis: "다수 지표는 긍정적이지만 단기 과열/거래량 혼조 요소가 남아 있음",
    items: [
      {
        indicator: "moving_average",
        signal: "positive",
        value: 386500,
        metrics: ["5MA > 20MA > 60MA", "정배열 유지"],
        detail: "이동평균 배열은 추세 지속 관점에서 긍정적입니다.",
        detail_source: "llm",
      },
      {
        indicator: "rsi",
        signal: "neutral",
        value: 67.4,
        metrics: ["RSI 67.4", "과열 직전"],
        detail: "과열 직전 구간이라 추가 상승 여지는 있지만 단기 피로 가능성도 함께 존재합니다.",
        detail_source: "llm",
      },
      {
        indicator: "volume",
        signal: "neutral",
        value: 0.0,
        metrics: ["평균 거래량 대비 강한 확장 없음"],
        detail: "가격 상승 대비 거래량 확인이 부족해 추세 확인 강도는 보통 수준입니다.",
        detail_source: "template_fallback",
      },
    ],
  },
  risks: {
    items: [
      {
        flag: "volume_not_confirmed",
        note: "거래량 확장이 동반되지 않으면 단기 상승 지속성은 약해질 수 있습니다.",
        ref_price: null,
      },
      {
        flag: "short_term_overheated",
        note: "RSI가 단기 과열권에 근접해 추격 진입 부담이 있습니다.",
        ref_price: 392000,
      },
    ],
  },
  charts: {
    available_periods: ["3m", "1y", "5y"],
    items: [
      { period: "3m", candle_unit: "D", display_order: 1, has_chart_data: true, annotation_count: 3 },
      { period: "1y", candle_unit: "W", display_order: 2, has_chart_data: true, annotation_count: 2 },
      { period: "5y", candle_unit: "M", display_order: 3, has_chart_data: true, annotation_count: 1 },
    ],
  },
  verification: {
    outcome: "passed",
    calc_passed: true,
    regime_passed: true,
    label_matched: true,
    regen_count: 0,
    failed_indicators: [],
    summary: "계산값, 국면 라벨, 최종 설명 간 주요 충돌이 없습니다.",
  },
  trace_summary: {
    trace_id: "demo-trace-technical-001",
    generation_path: {
      source: "KIS",
      interpretation_source: "llm",
      template_fallback_used: false,
      regen_count: 0,
      path_label: "normal",
    },
    data_quality: {
      data_status: "normal",
      available_periods: ["3m", "1y", "5y"],
      intraday_available: false,
      chart_count: 3,
      limited: false,
    },
    verification_summary: {
      outcome: "passed",
      calc_passed: true,
      regime_passed: true,
      label_matched: true,
      failed_indicators_count: 0,
    },
    stability: {
      confidence: 0.84,
      confidence_basis: "주요 지표 일치 + 단기 과열 변수만 일부 존재",
      verification_consistent: true,
    },
    flags: {
      used_fallback: false,
      had_regeneration: false,
      limited_data: false,
      verification_warning: false,
      has_intraday_context: false,
      has_daily_chart: true,
      has_weekly_chart: true,
      has_monthly_chart: true,
    },
  },
  trust_summary: {
    signal_quality: {
      signal_score: 0.46,
      signal_label: "약한 긍정",
      consensus: "weak_positive",
      confidence: 0.84,
      confidence_basis: "상승 추세 유지 + 단기 과열 경계",
    },
    data_quality: {
      data_status: "normal",
      available_periods: ["3m", "1y", "5y"],
      intraday_available: false,
      chart_count: 3,
      limited: false,
    },
    verification_gate: {
      outcome: "passed",
      calc_passed: true,
      regime_passed: true,
      label_matched: true,
      verification_warning: false,
    },
    source_linkage: {
      total_signal_items: 3,
      sourced_signal_items: 2,
      source_coverage_ratio: 0.67,
    },
  },
  followup_count: 2,
};

export const demoTechnicalCharts: TechnicalChartsReadModel = {
  report_id: "demo-technical-report",
  stock: demoTechnicalReport.stock,
  available_periods: ["3m", "1y", "5y"],
  charts: [
    {
      period: "3m",
      candle_unit: "D",
      display_order: 1,
      has_chart_data: true,
      annotation_count: 3,
      chart_data: {
        candle_unit: "D",
        candles: [
          { date: "2026-05-01", open: 318000, high: 325000, low: 314000, close: 322000, volume: 182000, trading_value: 0 },
          { date: "2026-05-22", open: 331000, high: 338000, low: 327000, close: 336000, volume: 205000, trading_value: 0 },
          { date: "2026-06-12", open: 344000, high: 352000, low: 340000, close: 349000, volume: 221000, trading_value: 0 },
          { date: "2026-06-26", open: 357000, high: 365000, low: 351000, close: 362000, volume: 194000, trading_value: 0 },
          { date: "2026-07-09", open: 372000, high: 389000, low: 369000, close: 386500, volume: 248000, trading_value: 0 },
        ],
        overlays: {
          moving_average: [
            {
              window: 5,
              points: [
                { date: "2026-05-01", value: 320000 },
                { date: "2026-05-22", value: 333000 },
                { date: "2026-06-12", value: 346000 },
                { date: "2026-06-26", value: 358000 },
                { date: "2026-07-09", value: 378000 },
              ],
            },
            {
              window: 20,
              points: [
                { date: "2026-05-01", value: 314000 },
                { date: "2026-05-22", value: 326000 },
                { date: "2026-06-12", value: 339000 },
                { date: "2026-06-26", value: 350000 },
                { date: "2026-07-09", value: 368000 },
              ],
            },
          ],
          support_resistance: [
            { type: "support", price: 362000, from: "2026-06-12", to: "2026-07-09", touch_count: 2 },
            { type: "resistance", price: 392000, from: "2026-07-01", to: "2026-07-09", touch_count: 1 },
          ],
        },
        subcharts: {
          rsi: {
            period: 14,
            overbought: 70,
            oversold: 30,
            points: [
              { date: "2026-05-01", value: 54 },
              { date: "2026-05-22", value: 58 },
              { date: "2026-06-12", value: 62 },
              { date: "2026-06-26", value: 65 },
              { date: "2026-07-09", value: 67.4 },
            ],
          },
          volume: {
            avg_window: 20,
            bars: [
              { date: "2026-05-01", volume: 182000, avg_volume: 176000, is_spike: false },
              { date: "2026-05-22", volume: 205000, avg_volume: 183000, is_spike: false },
              { date: "2026-06-12", volume: 221000, avg_volume: 191000, is_spike: false },
              { date: "2026-06-26", volume: 194000, avg_volume: 198000, is_spike: false },
              { date: "2026-07-09", volume: 248000, avg_volume: 204000, is_spike: true },
            ],
          },
        },
        annotations: [
          { id: "a1", kind: "support", date: "2026-06-12", price: 362000, label: "지지 확인", importance: "medium", source: "code", meta: {} },
          { id: "a2", kind: "breakout", date: "2026-06-26", price: 365000, label: "박스 상단 돌파", importance: "high", source: "code", meta: {} },
          { id: "a3", kind: "warning", date: "2026-07-09", price: 392000, label: "과열 주의", importance: "medium", source: "code", meta: {} },
        ],
      },
      annotations: [
        { id: "a1", label: "지지 확인", date: "2026-06-12", importance: "medium" },
        { id: "a2", label: "박스 상단 돌파", date: "2026-06-26", importance: "high" },
        { id: "a3", label: "과열 주의", date: "2026-07-09", importance: "medium" },
      ],
    },
    {
      period: "1y",
      candle_unit: "W",
      display_order: 2,
      has_chart_data: true,
      annotation_count: 2,
      chart_data: {
        candle_unit: "W",
        candles: [
          { date: "2025-08-01", open: 255000, high: 268000, low: 248000, close: 264000, volume: 800000, trading_value: 0 },
          { date: "2025-11-01", open: 273000, high: 286000, low: 269000, close: 281000, volume: 860000, trading_value: 0 },
          { date: "2026-02-01", open: 294000, high: 307000, low: 288000, close: 301000, volume: 910000, trading_value: 0 },
          { date: "2026-05-01", open: 318000, high: 332000, low: 314000, close: 327000, volume: 945000, trading_value: 0 },
          { date: "2026-07-09", open: 372000, high: 389000, low: 369000, close: 386500, volume: 990000, trading_value: 0 },
        ],
        overlays: {
          moving_average: [
            {
              window: 20,
              points: [
                { date: "2025-08-01", value: 258000 },
                { date: "2025-11-01", value: 274000 },
                { date: "2026-02-01", value: 291000 },
                { date: "2026-05-01", value: 320000 },
                { date: "2026-07-09", value: 356000 },
              ],
            },
          ],
          support_resistance: [
            { type: "support", price: 320000, from: "2026-04-01", to: "2026-07-09", touch_count: 2 },
          ],
        },
        subcharts: {
          rsi: {
            period: 14,
            overbought: 70,
            oversold: 30,
            points: [
              { date: "2025-08-01", value: 49 },
              { date: "2025-11-01", value: 55 },
              { date: "2026-02-01", value: 57 },
              { date: "2026-05-01", value: 61 },
              { date: "2026-07-09", value: 64 },
            ],
          },
          volume: {
            avg_window: 20,
            bars: [
              { date: "2025-08-01", volume: 800000, avg_volume: 760000, is_spike: false },
              { date: "2025-11-01", volume: 860000, avg_volume: 780000, is_spike: false },
              { date: "2026-02-01", volume: 910000, avg_volume: 810000, is_spike: false },
              { date: "2026-05-01", volume: 945000, avg_volume: 845000, is_spike: false },
              { date: "2026-07-09", volume: 990000, avg_volume: 880000, is_spike: false },
            ],
          },
        },
        annotations: [
          { id: "w1", kind: "trend", date: "2026-02-01", price: 301000, label: "주봉 상승 지속", importance: "medium", source: "code", meta: {} },
          { id: "w2", kind: "support", date: "2026-05-01", price: 320000, label: "주요 지지", importance: "medium", source: "code", meta: {} },
        ],
      },
      annotations: [
        { id: "w1", label: "주봉 상승 지속", date: "2026-02-01", importance: "medium" },
        { id: "w2", label: "주요 지지", date: "2026-05-01", importance: "medium" },
      ],
    },
    {
      period: "5y",
      candle_unit: "M",
      display_order: 3,
      has_chart_data: true,
      annotation_count: 1,
      chart_data: {
        candle_unit: "M",
        candles: [
          { date: "2022-07-01", open: 420000, high: 430000, low: 360000, close: 371000, volume: 1200000, trading_value: 0 },
          { date: "2023-07-01", open: 390000, high: 410000, low: 332000, close: 348000, volume: 1100000, trading_value: 0 },
          { date: "2024-07-01", open: 301000, high: 336000, low: 286000, close: 329000, volume: 980000, trading_value: 0 },
          { date: "2025-07-01", open: 260000, high: 282000, low: 246000, close: 274000, volume: 890000, trading_value: 0 },
          { date: "2026-07-09", open: 372000, high: 389000, low: 369000, close: 386500, volume: 990000, trading_value: 0 },
        ],
        overlays: {
          moving_average: [
            {
              window: 12,
              points: [
                { date: "2022-07-01", value: 385000 },
                { date: "2023-07-01", value: 362000 },
                { date: "2024-07-01", value: 334000 },
                { date: "2025-07-01", value: 301000 },
                { date: "2026-07-09", value: 342000 },
              ],
            },
          ],
          support_resistance: [
            { type: "resistance", price: 410000, from: "2022-01-01", to: "2026-07-09", touch_count: 2 },
          ],
        },
        subcharts: {
          rsi: {
            period: 14,
            overbought: 70,
            oversold: 30,
            points: [
              { date: "2022-07-01", value: 43 },
              { date: "2023-07-01", value: 41 },
              { date: "2024-07-01", value: 47 },
              { date: "2025-07-01", value: 51 },
              { date: "2026-07-09", value: 63 },
            ],
          },
          volume: {
            avg_window: 12,
            bars: [
              { date: "2022-07-01", volume: 1200000, avg_volume: 1180000, is_spike: false },
              { date: "2023-07-01", volume: 1100000, avg_volume: 1120000, is_spike: false },
              { date: "2024-07-01", volume: 980000, avg_volume: 1050000, is_spike: false },
              { date: "2025-07-01", volume: 890000, avg_volume: 970000, is_spike: false },
              { date: "2026-07-09", volume: 990000, avg_volume: 950000, is_spike: false },
            ],
          },
        },
        annotations: [
          { id: "m1", kind: "trend", date: "2026-07-09", price: 386500, label: "월봉 회복 추세", importance: "high", source: "code", meta: {} },
        ],
      },
      annotations: [{ id: "m1", label: "월봉 회복 추세", date: "2026-07-09", importance: "high" }],
    },
  ],
};

export const demoTechnicalTrace: TechnicalTraceDetailReadModel = {
  report_id: "demo-technical-report",
  overall: {
    total_steps: 5,
    total_duration_ms: null,
    llm_used: true,
    data_source_summary: "KIS 시세 + technical interpretation",
  },
  steps: [
    {
      step_order: 1,
      step_key: "data_collect",
      title: "시세 수집",
      source: "KIS",
      duration_ms: null,
      status: "ok",
      short_description: "기본 캔들 및 차트 소스 확보",
      llm_involved: false,
    },
    {
      step_order: 2,
      step_key: "regime_classify",
      title: "국면 분류",
      source: "code",
      duration_ms: null,
      status: "ok",
      short_description: "일·주·월 추세 정렬과 최종 국면 산출",
      llm_involved: false,
    },
    {
      step_order: 3,
      step_key: "signal_aggregate",
      title: "신호 집계",
      source: "code",
      duration_ms: null,
      status: "ok",
      short_description: "signal score, consensus, confidence 계산",
      llm_involved: false,
    },
    {
      step_order: 4,
      step_key: "interpret_report",
      title: "설명 생성",
      source: "llm",
      duration_ms: null,
      status: "ok",
      short_description: "구조화 해석과 key drivers 생성",
      llm_involved: true,
    },
    {
      step_order: 5,
      step_key: "verify",
      title: "검증",
      source: "code",
      duration_ms: null,
      status: "ok",
      short_description: "계산값/국면/문구 일치 여부 확인",
      llm_involved: false,
    },
  ],
};

export const demoTechnicalFollowups: TechnicalReportFollowupsReadModel = {
  report_id: "demo-technical-report",
  stock: demoTechnicalReport.stock,
  report_summary: {
    one_line_summary: demoTechnicalReport.summary.one_line_summary,
    directional_bias: demoTechnicalReport.summary.directional_bias,
    final_regime: demoTechnicalReport.summary.final_regime,
    as_of: demoTechnicalReport.meta.as_of,
  },
  followup_count: 2,
  followups: [
    {
      followup_id: "demo-followup-1",
      request_id: "fu-demo-1",
      question: "지금 추격 매수해도 괜찮아?",
      answer: "추세 자체는 유지되고 있지만 단기 과열 신호가 있어 즉시 추격보다는 눌림 확인 후 접근하는 편이 더 보수적입니다.",
      model_name: "gpt-demo",
      trace_id: "demo-followup-trace-1",
      created_at: "2026-07-09T10:18:00+09:00",
      answer_length: 67,
      context: {
        has_context_snapshot: true,
        base_report_regime: "uptrend_intact",
        base_report_bias: "bullish",
        base_report_data_status: "normal",
        base_report_signal_score: 0.46,
        base_report_as_of: "2026-07-09T10:15:00+09:00",
      },
    },
    {
      followup_id: "demo-followup-2",
      request_id: "fu-demo-2",
      question: "리스크는 어디를 보면 돼?",
      answer: "단기적으로는 362,000원 부근 지지 확인과 거래량 재확인이 핵심입니다. 해당 지지 이탈 시 단기 시나리오 신뢰도는 낮아질 수 있습니다.",
      model_name: "gpt-demo",
      trace_id: "demo-followup-trace-2",
      created_at: "2026-07-09T10:20:00+09:00",
      answer_length: 85,
      context: {
        has_context_snapshot: true,
        base_report_regime: "uptrend_intact",
        base_report_bias: "bullish",
        base_report_data_status: "normal",
        base_report_signal_score: 0.46,
        base_report_as_of: "2026-07-09T10:15:00+09:00",
      },
    },
  ],
};
