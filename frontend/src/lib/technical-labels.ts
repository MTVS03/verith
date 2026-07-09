export function biasLabel(value?: string | null): string {
  if (value === "bullish") return "상방 우세";
  if (value === "bearish") return "하방 우세";
  if (value === "neutral") return "중립";
  return "방향성 미정";
}

export function pathLabel(value?: string | null): string {
  if (value === "normal") return "LLM 생성";
  if (value === "regenerated") return "재생성";
  if (value === "template_fallback") return "템플릿 폴백";
  return "알 수 없음";
}

export function consensusLabel(value?: string | null): string {
  switch (value) {
    case "strong_positive":
      return "강한 긍정";
    case "weak_positive":
      return "약한 긍정";
    case "neutral":
      return "중립";
    case "weak_negative":
      return "약한 부정";
    case "strong_negative":
      return "강한 부정";
    default:
      return "판정 없음";
  }
}

export function regimeLabel(value?: string | null): string {
  switch (value) {
    case "uptrend_intact":
      return "상승 추세 유지";
    case "bullish_reversal_watch":
      return "상승 전환 관찰";
    case "sideways":
      return "횡보";
    case "downtrend":
      return "하락 추세";
    case "oversold_rebound_watch":
      return "과매도 반등 관찰";
    case "overheated":
      return "과열";
    case "unavailable":
      return "판정 불가";
    default:
      return value ?? "판정 없음";
  }
}

export function signalLabel(value?: string | null): string {
  if (value === "positive") return "긍정";
  if (value === "negative") return "부정";
  if (value === "neutral") return "중립";
  return value ?? "—";
}

export function signalTone(value?: string | null): "green" | "red" | "neutral" {
  if (value === "positive") return "green";
  if (value === "negative") return "red";
  return "neutral";
}

export function riskLabel(value?: string | null): string {
  switch (value) {
    case "volume_not_confirmed":
      return "거래량 확인 부족";
    case "near_support":
      return "지지 구간 근접";
    case "near_resistance":
      return "저항 구간 근접";
    case "mixed_signals":
      return "신호 엇갈림";
    case "overheated_momentum":
      return "과열 모멘텀 주의";
    case "overheated":
      return "과열 주의";
    case "weak_breakout":
      return "돌파 강도 약함";
    default:
      // 미매핑 flag: raw snake_case 를 그대로 노출하지 않고 Title Case 로 안전 변환.
      if (!value) return "리스크";
      return value
        .split("_")
        .filter(Boolean)
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ");
  }
}

export function verificationLabel(value?: string | null, warning?: boolean): string {
  if (warning) return "WARN";
  if (value === "passed") return "PASS";
  if (value === "template_fallback") return "FALLBACK";
  return value?.toUpperCase() ?? "—";
}
