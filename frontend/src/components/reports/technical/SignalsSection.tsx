"use client";

import { INDICATOR_LABELS, SIGNAL_LABELS, SOURCE_LABELS, labelOf } from "@/constants/labels";
import { StatusBadge, type BadgeTone } from "@/components/common/StatusBadge";
import type { SignalItem } from "@/types/technical-report";

/** signal(positive/neutral/negative) → 뱃지 tone. */
function signalTone(signal: string | null): BadgeTone {
  if (signal === "positive") return "positive";
  if (signal === "negative") return "negative";
  return "neutral";
}

function SignalCard({ item }: { item: SignalItem }) {
  return (
    <div className="p-4 bg-slate-50 border border-slate-200/60 rounded-xl space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-xs font-bold text-slate-800">
          {labelOf(INDICATOR_LABELS, item.indicator)}
        </h4>
        <StatusBadge
          tone={signalTone(item.signal)}
          label={labelOf(SIGNAL_LABELS, item.signal)}
        />
      </div>

      {item.metrics.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {item.metrics.map((m, i) => (
            <span
              key={i}
              className="px-2 py-0.5 rounded bg-white border border-slate-200 text-[10.5px] font-semibold text-slate-500 num"
            >
              {m}
            </span>
          ))}
        </div>
      )}

      {item.detail && (
        <p className="text-[11.5px] text-slate-500 leading-snug">{item.detail}</p>
      )}

      {item.detail_source && (
        <div className="text-[10px] text-slate-400">
          해석 출처 · {labelOf(SOURCE_LABELS, item.detail_source)}
        </div>
      )}
    </div>
  );
}

export function SignalsSection({ items }: { items: SignalItem[] }) {
  if (items.length === 0) {
    return (
      <p className="text-xs text-slate-400">표시할 지표 신호가 없습니다.</p>
    );
  }
  return (
    <div className="grid md:grid-cols-2 gap-3">
      {items.map((item) => (
        <SignalCard key={item.indicator} item={item} />
      ))}
    </div>
  );
}
