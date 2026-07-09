import clsx from "clsx";

import type { NewsGauge } from "@/types/news";

// 감성 게이지 — 긍정(emerald)·중립(slate)·부정(rose) 3분할 막대 + 라벨/건수.
// overall_gauge 와 이벤트별 gauge 에 함께 쓴다(같은 어휘로 대조).
export function NewsSentimentBar({ gauge, size = "md" }: { gauge: NewsGauge; size?: "sm" | "md" }) {
  const { positive_pct, neutral_pct, negative_pct, positive, neutral, negative, total } = gauge;
  const big = size === "md";
  return (
    <div className="w-full">
      <div className={clsx("flex overflow-hidden rounded-full bg-slate-100", big ? "h-3" : "h-2")}>
        <div className="h-full bg-emerald-500" style={{ width: `${positive_pct}%` }} />
        <div className="h-full bg-slate-300" style={{ width: `${neutral_pct}%` }} />
        <div className="h-full bg-rose-500" style={{ width: `${negative_pct}%` }} />
      </div>
      <div
        className={clsx(
          "mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 tabular-nums",
          big ? "text-xs" : "text-[11px]",
        )}
      >
        <span className="flex items-center gap-1 font-semibold text-emerald-600">
          <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />긍정 {positive} ({positive_pct}%)
        </span>
        <span className="flex items-center gap-1 font-semibold text-slate-500">
          <span className="inline-block h-2 w-2 rounded-full bg-slate-300" />중립 {neutral} ({neutral_pct}%)
        </span>
        <span className="flex items-center gap-1 font-semibold text-rose-600">
          <span className="inline-block h-2 w-2 rounded-full bg-rose-500" />부정 {negative} ({negative_pct}%)
        </span>
        <span className="text-slate-400">· 총 {total}건</span>
      </div>
    </div>
  );
}
