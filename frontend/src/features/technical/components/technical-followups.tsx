"use client";

import { MessageSquare, HelpCircle, Sparkles } from "lucide-react";
import { formatDateTime } from "@/lib/format";
import type { TechnicalReportFollowupsReadModel } from "@/types/technical";

export function TechnicalFollowups({
  followups,
}: {
  followups: TechnicalReportFollowupsReadModel;
}) {
  const items = followups.followups;

  return (
    <section
      id="a-followups"
      className="border border-[#f1f5f9] rounded-2xl p-6 shadow-[0_1px_2px_rgba(15,23,42,0.04),0_1px_3px_rgba(15,23,42,0.06)] bg-white"
    >
      <div className="flex items-center justify-between border-b border-[#f1f5f9] pb-3 mb-5">
        <h2 className="flex items-center gap-2.5 text-base font-bold text-[#0f172a] m-0">
          <MessageSquare className="w-[19px] h-[19px] text-[#334155]" /> 질의응답 기록
        </h2>
        <span className="text-[11px] font-semibold text-[#64748b] bg-[#f8fafc] px-2.5 py-1 rounded-full">
          {followups.followup_count}개의 대화
        </span>
      </div>

      {items.length ? (
        <div className="space-y-6">
          {items.map((item) => (
            <div
              key={item.followup_id}
              className="border border-[#e2e8f0] rounded-2xl p-5 bg-[#f8fafc] flex flex-col gap-4 shadow-xs"
            >
              {/* Metadata row */}
              <div className="flex items-center justify-between flex-wrap gap-2 text-xs text-[#94a3b8]">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-[#4f46e5] bg-indigo-50 border border-indigo-100 rounded px-1.5 py-0.5">
                    {item.model_name ?? "AI 모델"}
                  </span>
                  {item.trace_id && (
                    <span className="font-mono text-[10.5px]">trace: {item.trace_id}</span>
                  )}
                </div>
                <span className="font-tabular">
                  {item.created_at ? formatDateTime(item.created_at) : "—"}
                </span>
              </div>

              {/* Question card */}
              <div className="flex items-start gap-3 bg-white border border-[#e2e8f0] rounded-xl p-4">
                <div className="grid h-8 w-8 place-items-center rounded-lg bg-slate-100 text-slate-500 flex-shrink-0">
                  <HelpCircle className="w-4.5 h-4.5" />
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-bold text-[#94a3b8] uppercase tracking-wider">Question</p>
                  <p className="mt-1 text-sm font-semibold text-[#0f172a] leading-relaxed">
                    {item.question ?? "질문이 없습니다."}
                  </p>
                </div>
              </div>

              {/* Answer card */}
              <div className="flex items-start gap-3 bg-white border border-[#e2e8f0] rounded-xl p-4">
                <div className="grid h-8 w-8 place-items-center rounded-lg bg-indigo-50 text-[#4f46e5] flex-shrink-0">
                  <Sparkles className="w-4.5 h-4.5" />
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-bold text-[#94a3b8] uppercase tracking-wider">Answer</p>
                  <p className="mt-1 text-sm leading-relaxed text-[#334155] whitespace-pre-wrap">
                    {item.answer ?? "답변이 진행 중이거나 없습니다."}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-slate-200 bg-[#f8fafc] py-12 text-center text-sm text-slate-400">
          아직 기록된 후속 질문이 없습니다.
        </div>
      )}
    </section>
  );
}
