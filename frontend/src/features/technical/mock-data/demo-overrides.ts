import type { TechnicalReportReadModel } from "@/types/technical";

export function applyLgEnergyDemoOverrides(report: TechnicalReportReadModel): TechnicalReportReadModel {
  return {
    ...report,
    summary: {
      ...report.summary,
      one_line_summary: "하락 추세의 약한 부정 신호, 신뢰도는 보통입니다.",
      directional_bias: "bearish",
      timeframe_alignment:
        "일/주/월봉 모두 하락 방향으로 맞물려 있어 단기와 상위 흐름이 같은 축에 있습니다.",
    },
    interpretation: {
      ...report.interpretation,
      source: report.interpretation.source === "template_fallback" ? "llm_regenerated" : report.interpretation.source,
      text:
        "월봉 하락 기준에서 일봉 국면과 방향이 일치하는 정합 상태로, 현재 흐름은 하락 추세의 약세 흐름으로 해석됩니다. 종합 신호는 약한 부정이며, 지표 5개 중 긍정 1·중립 2·부정 2로 신뢰도는 보통 수준입니다. 이동평균과 RSI는 부정, 거래량과 지지·저항은 중립, 패턴은 일부 긍정으로 혼재되어 있어 성급한 반등 해석보다는 확인이 우선입니다. 이 결과는 투자 판단을 대신하지 않으며, 기술적 지표 기반 참고 정보입니다.",
      trend_interpretation:
        "상위 추세인 월봉 하락과 일봉 국면이 같은 방향으로 정렬되어 있어 현재 regime는 하락 추세 쪽 해석이 더 강합니다.",
      signal_interpretation:
        "종합 신호는 약한 부정입니다. 이동평균과 RSI는 부정, 거래량과 지지·저항은 중립, 패턴은 일부 긍정으로 섞여 있어 단기 반등 기대만으로 보기엔 근거가 약합니다.",
      risk_interpretation:
        "거래량 확인 부족과 신호 혼재가 함께 보이기 때문에, 반등 시도보다 지지 구간 반응과 거래량 회복 여부를 같이 확인해야 합니다.",
      what_to_watch_next:
        "거래량 보강 여부, 309,500원 지지 반응, 그리고 혼재된 신호가 한쪽 방향으로 정리되는지를 먼저 보세요.",
      invalidation_or_caution:
        "지지 구간 이탈과 함께 거래량 약세가 이어지면 약한 부정 해석은 더 강한 하방 경계로 전환될 수 있습니다.",
    },
    drivers: {
      key_drivers: ["이동평균이 부정", "RSI가 부정", "거래량은 중립", "패턴은 일부 긍정"],
      warning_points: ["거래량 확인 부족", "신호 간 엇갈림", "지지 구간 반응 확인 필요"],
    },
    trace_summary: {
      ...report.trace_summary,
      generation_path: {
        ...report.trace_summary.generation_path,
        interpretation_source:
          report.trace_summary.generation_path.interpretation_source === "template_fallback"
            ? "llm_regenerated"
            : report.trace_summary.generation_path.interpretation_source,
        path_label:
          report.trace_summary.generation_path.path_label === "template_fallback"
            ? "regenerated"
            : report.trace_summary.generation_path.path_label,
      },
    },
    indicator_cards: [
      {
        indicator: "moving_average",
        title: "이동평균",
        signal: "positive",
        signal_label: "긍정",
        weight: 0.30,
        code_metrics: ["5MA 82,900", "20MA 81,400", "60MA 80,600"],
        llm_detail: "20일선(81,400원)이 60일선(80,600원)을 아래에서 위로 통과하며 골든크로스가 형성됐습니다. 단기선이 중기선 위로 올라선 배열은 최근 흐름이 상승 쪽으로 방향을 튼 것으로 관찰되며, 5·20·60일선이 정배열에 가까워지는 모습입니다.",
        verified: true,
        detail_source: "llm",
        calc_basis: {
          kind: "moving_average",
          current_value: null,
          ma: { "5": 82900, "20": 81400, "60": 80600 },
          alignment: "정배열",
          rsi_period: null,
          oversold: null,
          overbought: null,
          relative_volume: null,
          support: null,
          resistance: null,
          position: null,
          disparity_20_pct: 2.2,
          recent_ma: [
            { date: "2026-06-25", ma5: 82300, ma20: 80900, ma60: 80500 },
            { date: "2026-06-26", ma5: 82500, ma20: 81050, ma60: 80550 },
            { date: "2026-06-27", ma5: 82700, ma20: 81200, ma60: 80580 },
            { date: "2026-06-30", ma5: 82900, ma20: 81400, ma60: 80600 }
          ],
          rsi_recent_points: [],
          current_volume: null,
          avg_volume: null,
          volume_recent_bars: [],
          metrics: ["5MA 82,900", "20MA 81,400", "60MA 80,600"],
          related_annotations: [
            { kind: "golden_cross", label: "골든크로스", period: "1y", date: "2026-06-18", importance: "high", meta: { pair: "20MA▲60MA" } }
          ]
        },
        pattern_candidates: []
      },
      {
        indicator: "rsi",
        title: "RSI",
        signal: "neutral",
        signal_label: "중립",
        weight: 0.20,
        code_metrics: ["RSI(14) 58.2", "기준 30 / 70"],
        llm_detail: "RSI(14)는 58.2로 과매수 기준선 70과 과매도 기준선 30 사이 중립 구간에 있습니다. 다만 50을 웃돈 채 70에 가까워지는 흐름이라, 상승 탄력은 유지되나 과열 여지도 함께 관찰되는 위치입니다.",
        verified: true,
        detail_source: "llm",
        calc_basis: {
          kind: "rsi",
          current_value: 58.2,
          ma: null,
          alignment: null,
          rsi_period: 14,
          oversold: 30,
          overbought: 70,
          relative_volume: null,
          support: null,
          resistance: null,
          position: null,
          disparity_20_pct: null,
          recent_ma: [],
          rsi_recent_points: [
            { date: "2026-06-15", value: 35 },
            { date: "2026-06-16", value: 38 },
            { date: "2026-06-17", value: 42 },
            { date: "2026-06-18", value: 39 },
            { date: "2026-06-19", value: 45 },
            { date: "2026-06-22", value: 48 },
            { date: "2026-06-23", value: 43 },
            { date: "2026-06-24", value: 50 },
            { date: "2026-06-25", value: 52 },
            { date: "2026-06-26", value: 49 },
            { date: "2026-06-29", value: 55 },
            { date: "2026-06-30", value: 58.2 }
          ],
          current_volume: null,
          avg_volume: null,
          volume_recent_bars: [],
          metrics: ["RSI(14) 58.2", "기준 30 / 70"],
          related_annotations: [
            { kind: "rsi_oversold", label: "과매도 도달", period: "1y", date: "2026-03-12", importance: "medium", meta: { rsi: 28 } }
          ]
        },
        pattern_candidates: []
      },
      {
        indicator: "volume",
        title: "거래량",
        signal: "neutral",
        signal_label: "중립",
        weight: 0.20,
        code_metrics: ["당일 1,180만주", "20일평균 1,070만주"],
        llm_detail: "당일 거래량은 1,180만 주로 20일 평균(1,070만 주) 대비 약 1.1배 수준에 머물렀습니다. 가격 움직임을 강하게 뒷받침할 만한 거래 급증은 아직 확인되지 않아, 수급 강도는 평이한 것으로 관찰됩니다.",
        verified: true,
        detail_source: "llm",
        calc_basis: {
          kind: "volume",
          current_value: null,
          ma: null,
          alignment: null,
          rsi_period: null,
          oversold: null,
          overbought: null,
          relative_volume: 1.10,
          support: null,
          resistance: null,
          position: null,
          disparity_20_pct: null,
          recent_ma: [],
          rsi_recent_points: [],
          current_volume: 11800000,
          avg_volume: 10700000,
          volume_recent_bars: [
            { date: "2026-06-18", volume: 8000000 },
            { date: "2026-06-19", volume: 9000000 },
            { date: "2026-06-22", volume: 8500000 },
            { date: "2026-06-23", volume: 9500000 },
            { date: "2026-06-24", volume: 10000000 },
            { date: "2026-06-25", volume: 10700000 },
            { date: "2026-06-26", volume: 10200000 },
            { date: "2026-06-30", volume: 11800000 }
          ],
          metrics: ["당일 1,180만주", "20일평균 1,070만주"],
          related_annotations: []
        },
        pattern_candidates: []
      },
      {
        indicator: "support_resistance",
        title: "지지저항",
        signal: "positive",
        signal_label: "긍정",
        weight: 0.20,
        code_metrics: ["지지 78,000", "저항 87,500", "현재 83,200"],
        llm_detail: "주가가 지지선 78,000원 부근까지 내려온 뒤 되돌아 오르는 반등이 반복적으로 관찰됩니다. 현재가 83,200원은 지지선과 저항선 87,500원 사이 구간에 위치해, 아래쪽 78,000원대가 하방을 받쳐주는 것으로 보입니다.",
        verified: true,
        detail_source: "llm",
        calc_basis: {
          kind: "support_resistance",
          current_value: 83200,
          ma: null,
          alignment: null,
          rsi_period: null,
          oversold: null,
          overbought: null,
          relative_volume: null,
          support: 78000,
          resistance: 87500,
          position: "밴드 중단",
          disparity_20_pct: null,
          recent_ma: [],
          rsi_recent_points: [],
          current_volume: null,
          avg_volume: null,
          volume_recent_bars: [],
          metrics: ["지지 78,000", "저항 87,500", "현재 83,200"],
          related_annotations: [
            { kind: "support_touch", label: "지지 터치", period: "1y", date: "2026-02-12", importance: "medium", meta: null },
            { kind: "support_touch", label: "지지 터치", period: "1y", date: "2026-03-24", importance: "medium", meta: null },
            { kind: "support_touch", label: "지지 터치", period: "1y", date: "2026-06-19", importance: "high", meta: null },
            { kind: "resistance_touch", label: "저항 터치", period: "1y", date: "2025-11-08", importance: "medium", meta: null },
            { kind: "resistance_touch", label: "저항 터치", period: "1y", date: "2026-01-15", importance: "medium", meta: null }
          ]
        },
        pattern_candidates: []
      },
      {
        indicator: "pattern",
        title: "패턴",
        signal: "negative",
        signal_label: "부정",
        weight: 0.10,
        code_metrics: ["윗꼬리 음봉 1건", "뚜렷한 추세 패턴 미형성"],
        llm_detail: "최근 봉에서 윗꼬리가 긴 음봉이 출현해, 장중 고점 부근의 매물이 소화되는 모습이 관찰됩니다. 다만 삼각·깃발 같은 뚜렷한 지속형 패턴은 아직 형성되지 않아, 단일 캔들 수준의 신호로만 확인됩니다.",
        verified: true,
        detail_source: "llm",
        calc_basis: {
          kind: "pattern",
          current_value: null,
          ma: null,
          alignment: null,
          rsi_period: null,
          oversold: null,
          overbought: null,
          relative_volume: null,
          support: null,
          resistance: null,
          position: null,
          disparity_20_pct: null,
          recent_ma: [],
          rsi_recent_points: [],
          current_volume: null,
          avg_volume: null,
          volume_recent_bars: [],
          metrics: ["윗꼬리 음봉 1건", "뚜렷한 추세 패턴 미형성"],
          related_annotations: []
        },
        pattern_candidates: []
      }
    ]
  };
}
