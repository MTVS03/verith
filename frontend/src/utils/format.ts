/**
 * 표시 변환(format) 순수 함수 모음.
 * 프론트는 분석값을 새로 계산하지 않는다 — 여기 함수는 "표시용 변환"만 한다(가이드라인 §3.2).
 */

import { CONFIDENCE_LEVEL_LABELS } from "@/constants/labels";

/** §6 confidence(0.0~1.0 float) → 구간 코드값. 경계값은 enums.md 기준(MVP 잠정). */
export function confidenceLevel(
  confidence: number | null | undefined,
): "high" | "medium" | "low" | null {
  if (confidence == null) return null;
  if (confidence >= 0.7) return "high";
  if (confidence >= 0.4) return "medium";
  return "low";
}

/** confidence float → 표시 라벨(높음/보통/낮음). 없으면 null. */
export function confidenceLevelLabel(
  confidence: number | null | undefined,
): string | null {
  const level = confidenceLevel(confidence);
  return level ? CONFIDENCE_LEVEL_LABELS[level] : null;
}

/** confidence float → 백분율 정수(0~100). 없으면 null. */
export function confidencePercent(
  confidence: number | null | undefined,
): number | null {
  if (confidence == null) return null;
  return Math.round(confidence * 100);
}

/** ISO datetime → YYYY-MM-DD(로컬). 파싱 실패/없음이면 빈 문자열. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** 6자리 종목코드 형식 검증(앞자리 0 보존). */
export function isValidTicker(ticker: string): boolean {
  return /^\d{6}$/.test(ticker);
}
