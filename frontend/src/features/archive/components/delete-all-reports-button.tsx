"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";

import { deleteAllTechnicalReports } from "@/api/technical";

// technical 보관함 목록 **전체 삭제** 버튼. 되돌릴 수 없는 대량 작업이라 확인을 강하게 받는다.
export function DeleteAllReportsButton({ count }: { count: number }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);

  const onDeleteAll = async () => {
    if (busy || isPending) return;
    if (!window.confirm(`technical 리포트 ${count}개를 모두 삭제할까요? 되돌릴 수 없습니다.`)) return;
    setBusy(true);
    try {
      await deleteAllTechnicalReports();
      startTransition(() => router.refresh());
    } catch {
      window.alert("전체 삭제에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(false);
    }
  };

  const disabled = busy || isPending;
  return (
    <button
      type="button"
      onClick={onDeleteAll}
      disabled={disabled}
      className="inline-flex items-center gap-1.5 rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2 text-sm font-semibold text-rose-600 transition hover:bg-rose-100 disabled:opacity-50"
    >
      <Trash2 className="h-4 w-4" />
      {disabled ? "삭제 중…" : "전체 삭제"}
    </button>
  );
}
