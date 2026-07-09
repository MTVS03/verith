/**
 * enum 코드값 → 표시 라벨(한글) 중앙 관리.
 * 정본: ai/src/agents/technical/docs/enums.md (§1~§10)
 *
 * 프론트는 여기 없는 라벨을 임의로 만들지 않는다. enums.md 가 코드·DB·프론트 3계층의 단일 기준이며,
 * 값 추가/변경 시 enums.md 를 먼저 고치고 이 파일에 반영한다.
 */

/** §1 regime — final_regime / daily_regime */
export const REGIME_LABELS: Record<string, string> = {
  oversold_rebound_watch: "과매도 반등 관찰",
  overheated: "과열",
  bullish_reversal_watch: "상승 전환 관찰",
  uptrend_intact: "상승 추세 유지",
  downtrend: "하락 추세",
  sideways: "횡보",
  unavailable: "판단 불가",
};

/** §2 consensus (신호 종합) */
export const CONSENSUS_LABELS: Record<string, string> = {
  strong_positive: "긍정 우세",
  weak_positive: "약한 긍정",
  neutral: "중립",
  weak_negative: "약한 부정",
  strong_negative: "부정 우세",
};

/** §3 signal (지표별 개별 신호) */
export const SIGNAL_LABELS: Record<string, string> = {
  positive: "긍정",
  neutral: "중립",
  negative: "부정",
};

/** §4 trend (타임프레임 추세) — weekly_trend / monthly_trend */
export const TREND_LABELS: Record<string, string> = {
  up: "상승",
  down: "하락",
  sideways: "횡보",
  unavailable: "판단 불가",
};

/** §5 alignment_flag (멀티프레임 정합) */
export const ALIGNMENT_LABELS: Record<string, string> = {
  aligned: "정합",
  counter_trend: "역행",
  neutral: "중립",
};

/** §6 confidence_level (신뢰도 구간) — 표시용 */
export const CONFIDENCE_LEVEL_LABELS: Record<string, string> = {
  high: "높음",
  medium: "보통",
  low: "낮음",
};

/** §7 risk_flags (리스크 라벨) */
export const RISK_FLAG_LABELS: Record<string, string> = {
  volume_not_confirmed: "거래량 확인 약함",
  near_resistance: "저항 구간 근접",
  near_support: "지지 구간 근접",
  mixed_signals: "신호 엇갈림",
  overheated_momentum: "단기 과열 관찰",
  counter_higher_trend: "상위 추세와 역행",
  low_liquidity: "유동성 낮음",
};

/** §8 data_status (데이터/분석 상태) */
export const DATA_STATUS_LABELS: Record<string, string> = {
  normal: "정상",
  stale_cache: "최신 시세 미반영",
  data_limited: "데이터 제한",
  regime_unavailable: "판단 불가",
};

/** §9 해석 출처 (interpretation_source / detail_source) */
export const SOURCE_LABELS: Record<string, string> = {
  llm: "AI 설명",
  llm_regenerated: "AI 재생성 설명",
  template_fallback: "검증된 템플릿 설명",
};

/** §10 period (차트 기간) */
export const PERIOD_LABELS: Record<string, string> = {
  "3m": "3개월",
  "1y": "1년",
  "5y": "5년",
};

/** 지표명(technical_signals[].indicator) — 정본: frontend_mapping.md 지표 표시 라벨 */
export const INDICATOR_LABELS: Record<string, string> = {
  moving_average: "이동평균",
  rsi: "RSI",
  volume: "거래량",
  support_resistance: "지지·저항",
  pattern: "패턴",
};

/** agent_type — 보관함 필터/뱃지용(도메인 리포트 종류) */
export const AGENT_TYPE_LABELS: Record<string, string> = {
  technical: "가격/기술",
  fundamental: "재무/펀더멘탈",
  news: "뉴스/심리",
};

/**
 * 알 수 없는 코드값이 와도 화면이 깨지지 않게 하는 안전 조회.
 * 매핑에 없으면 코드값을 그대로 노출(개발 중 누락 발견용).
 */
export function labelOf(
  map: Record<string, string>,
  code: string | null | undefined,
  fallback = "—",
): string {
  if (!code) return fallback;
  return map[code] ?? code;
}
