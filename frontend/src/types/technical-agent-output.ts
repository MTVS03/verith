/**
 * Technical 에이전트 출력(TechnicalAgentOutput) — 슈퍼바이저 results[].output 형태.
 * 정본: ai/src/agents/technical/schemas/contracts.py
 *
 * backend read model(TechnicalReportReadModel)과 같은 정보를 담되, 의미 단위 중첩 구조를 유지한다
 * (regime/signal/interpretation ...). 슈퍼바이저 경로에서는 이 shape 로 온다.
 */

import type { SignalItem } from "./technical-report";

export interface TechRegime {
  daily_regime: string | null;
  final_regime: string | null;
  weekly_trend: string | null;
  monthly_trend: string | null;
  alignment_flag: string | null;
  regime_context: string | null;
}

export interface TechSignal {
  consensus: string | null;
  signal_score: number | null;
  confidence: number | null;
  confidence_level: string | null; // high/medium/low — 에이전트가 제공
  confidence_basis: string | null;
}

export interface TechRiskItem {
  flag: string;
  note: string | null;
  ref_price: number | null;
}

export interface TechInterpretation {
  text: string | null;
  source: string | null;
  one_line_summary: string | null;
  directional_bias: string | null;
  key_drivers: string[];
  warning_points: string[];
  risk_interpretation: string | null;
  what_to_watch_next: string | null;
}

export interface TechVerification {
  calc_passed: boolean | null;
  regime_passed: boolean | null;
  label_matched: boolean | null;
  outcome: string | null;
  regen_count: number | null;
}

export interface TechnicalAgentOutput {
  ticker: string;
  as_of: string;
  source: string;
  data_status: string;
  trace_id: string;
  regime: TechRegime;
  signal: TechSignal | null;
  technical_signals: SignalItem[];
  risk: { items: TechRiskItem[] } | null;
  interpretation: TechInterpretation;
  verification: TechVerification;
}
