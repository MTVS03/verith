import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * 상태 뱃지 — 의미를 색상만이 아니라 **텍스트(라벨) + 아이콘**으로도 전달한다(가이드라인 §10.1).
 * tone 은 시맨틱 축이며 라벨 문자열은 호출부(중앙 상수)에서 전달한다.
 */
export type BadgeTone =
  | "positive"
  | "negative"
  | "neutral"
  | "warning"
  | "verified";

const TONE_CLASS: Record<BadgeTone, string> = {
  positive: "bg-emerald-50 text-emerald-600 border-emerald-100",
  negative: "bg-rose-50 text-rose-600 border-rose-100",
  neutral: "bg-slate-100 text-slate-500 border-slate-200",
  warning: "bg-amber-50 text-amber-600 border-amber-100",
  verified: "bg-emerald-50 text-emerald-600 border-emerald-100",
};

interface StatusBadgeProps {
  label: string;
  tone?: BadgeTone;
  icon?: ReactNode;
  className?: string;
}

export function StatusBadge({
  label,
  tone = "neutral",
  icon,
  className,
}: StatusBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full border text-[10.5px] font-bold",
        TONE_CLASS[tone],
        className,
      )}
    >
      {icon}
      {label}
    </span>
  );
}
