import { Check, X, CircleSlash, type LucideIcon } from "lucide-react";
import clsx from "clsx";

// 스텝 상태 — 진행 연출 + 실제 결과(정직 표시).
// pending/active 는 연출, success/failed/skipped 는 supervisor 실제 결과.
export type StepState = "pending" | "active" | "success" | "failed" | "skipped";

export type PipelineStep = {
  key: string;
  label: string;
  desc: string;
  icon: LucideIcon;
  state: StepState;
};

const STATUS_TEXT: Record<StepState, string> = {
  pending: "대기 중",
  active: "분석 중",
  success: "검증 완료",
  failed: "실패",
  skipped: "건너뜀",
};

function TypingDots() {
  return (
    <span className="inline-flex gap-0.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1 w-1 animate-pulse rounded-full bg-indigo-500"
          style={{ animationDelay: `${i * 0.2}s` }}
        />
      ))}
    </span>
  );
}

function StepRow({ step }: { step: PipelineStep }) {
  const Icon = step.icon;
  const done = step.state === "success" || step.state === "failed" || step.state === "skipped";

  return (
    <div
      className={clsx(
        "flex items-start gap-3 rounded-xl p-2 transition duration-150",
        step.state === "active" && "bg-indigo-50/50 opacity-100",
        step.state === "pending" && "opacity-40",
        done && "opacity-100",
      )}
    >
      <span
        className={clsx(
          "mt-0.5 grid h-7 w-7 place-items-center rounded-lg",
          step.state === "active" && "bg-indigo-600 text-white",
          step.state === "success" && "bg-emerald-100 text-emerald-600",
          step.state === "failed" && "bg-rose-100 text-rose-600",
          step.state === "skipped" && "bg-slate-100 text-slate-400",
          step.state === "pending" && "bg-slate-100 text-slate-400",
        )}
      >
        {step.state === "success" ? (
          <Check className="h-4 w-4" />
        ) : step.state === "failed" ? (
          <X className="h-4 w-4" />
        ) : step.state === "skipped" ? (
          <CircleSlash className="h-4 w-4" />
        ) : (
          <Icon className="h-4 w-4" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[12.5px] font-bold text-slate-700">{step.label}</div>
        <div className="mt-0.5 text-[11px] leading-snug text-slate-400">{step.desc}</div>
      </div>
      <span
        className={clsx(
          "mt-0.5 text-[11px] font-bold",
          step.state === "success" && "text-emerald-600",
          step.state === "failed" && "text-rose-500",
          step.state === "skipped" && "text-slate-400",
          step.state === "pending" && "text-slate-400",
        )}
      >
        {step.state === "active" ? <TypingDots /> : STATUS_TEXT[step.state]}
      </span>
    </div>
  );
}

export function PipelineBox({ steps, percent }: { steps: PipelineStep[]; percent: number }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-[0_10px_25px_-5px_rgba(15,23,42,0.08)]">
      <div className="flex items-center justify-between border-b border-slate-100 p-5">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-indigo-600" />
          </span>
          <span className="text-[13.5px] font-bold text-slate-800">멀티에이전트 파이프라인 분석 중</span>
        </div>
        <span className="text-sm font-extrabold text-indigo-600 tabular-nums">{percent}%</span>
      </div>
      <div className="space-y-3.5 bg-slate-50/50 px-5 py-4">
        <div className="h-2 overflow-hidden rounded-full bg-slate-200/60">
          <div
            className="h-full rounded-full bg-indigo-600 transition-all duration-300"
            style={{ width: `${percent}%` }}
          />
        </div>
        <div className="space-y-1.5">
          {steps.map((s) => (
            <StepRow key={s.key} step={s} />
          ))}
        </div>
      </div>
    </div>
  );
}
