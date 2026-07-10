"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { ChevronLeft, Download, Trash2 } from "lucide-react";

import { deleteNewsReport } from "@/api/news";

// news 상세 상단 액션바 — technical 과 동일 구성: 목록 복귀 · PDF 다운로드(인쇄) · 삭제.
export function NewsActions({ reportId }: { reportId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [isPending, startTransition] = useTransition();

  const onPrint = () => window.print();

  const onDelete = async () => {
    if (busy) return;
    if (!window.confirm("이 리포트를 삭제할까요? 되돌릴 수 없습니다.")) return;
    setBusy(true);
    try {
      await deleteNewsReport(reportId);
      startTransition(() => router.push("/?agent_type=news"));
    } catch {
      window.alert("삭제에 실패했습니다. 잠시 후 다시 시도해 주세요.");
      setBusy(false);
    }
  };

  const disabled = busy || isPending;
  return (
    <div className="no-print mb-5 flex items-center justify-between">
      <Link
        href="/?agent_type=news"
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
          onClick={onPrint}
          className="flex items-center gap-1.5 rounded-xl bg-[#4f46e5] px-3.5 py-2.5 text-[13px] font-bold text-white shadow-[0_4px_10px_-3px_rgba(79,70,229,0.5)] transition-colors hover:bg-[#4338ca]"
        >
          <Download className="h-4 w-4" />
          <span>PDF 다운로드</span>
        </button>
      </div>
    </div>
  );
}
