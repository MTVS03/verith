"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { ChevronLeft, Printer, Trash2 } from "lucide-react";

import { deleteFlowReport } from "@/api/flow";

// flow 상세 상단 액션바 — 목록 복귀 · 인쇄(PDF) · 삭제. flow 상세는 iframe 이 아니라
// React 렌더라서 window.print() 로 바로 인쇄/PDF 저장이 된다(technical 과 동일).
export function FlowActions({ reportId }: { reportId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [isPending, startTransition] = useTransition();

  const onDelete = async () => {
    if (busy) return;
    if (!window.confirm("이 리포트를 삭제할까요? 되돌릴 수 없습니다.")) return;
    setBusy(true);
    try {
      await deleteFlowReport(reportId);
      startTransition(() => router.push("/?agent_type=flow"));
    } catch {
      window.alert("삭제에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      setBusy(false);
    }
  };

  const disabled = busy || isPending;
  return (
    <div className="mb-5 flex items-center justify-between print:hidden">
      <Link
        href="/?agent_type=flow"
        className="flex items-center gap-1.5 text-[13px] font-bold text-[#4f46e5] transition-colors hover:text-[#4338ca]"
      >
        <ChevronLeft className="h-4 w-4" /> 리포트 목록으로 돌아가기
      </Link>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onDelete}
          disabled={disabled}
          className="flex items-center gap-1.5 rounded-xl border border-rose-100 bg-rose-50/60 px-3.5 py-2.5 text-[13px] font-bold text-rose-600 transition-colors hover:bg-rose-100 disabled:opacity-50"
        >
          <Trash2 className="h-4 w-4" />
          <span>{disabled ? "삭제 중…" : "삭제"}</span>
        </button>
        <button
          type="button"
          onClick={() => window.print()}
          className="flex items-center gap-1.5 rounded-xl bg-[#4f46e5] px-3.5 py-2.5 text-[13px] font-bold text-white shadow-[0_4px_10px_-3px_rgba(79,70,229,0.5)] transition-colors hover:bg-[#4338ca]"
        >
          <Printer className="h-4 w-4" />
          <span>인쇄 · PDF 저장</span>
        </button>
      </div>
    </div>
  );
}
