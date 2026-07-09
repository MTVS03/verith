"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";

import { deleteTechnicalReport } from "@/api/technical";

// 보관함 카드의 삭제 버튼. 카드 전체가 <Link> 라 클릭 전파를 막고(navigate 방지), 브라우저에서
// 백엔드 DELETE 직접 호출(백엔드 CORS 허용) → 성공 시 router.refresh() 로 목록(서버 컴포넌트) 재조회.
export function DeleteReportButton({ reportId }: { reportId: string }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);

  const onDelete = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (busy || isPending) return;
    if (!window.confirm("이 리포트를 삭제할까요? 되돌릴 수 없습니다.")) return;
    setBusy(true);
    try {
      await deleteTechnicalReport(reportId);
      startTransition(() => router.refresh());
    } catch {
      window.alert("삭제에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(false);
    }
  };

  const disabled = busy || isPending;
  return (
    <button
      type="button"
      onClick={onDelete}
      disabled={disabled}
      aria-label="리포트 삭제"
      className="inline-flex items-center gap-1 rounded-lg border border-rose-100 bg-rose-50/60 px-2.5 py-1.5 text-xs font-semibold text-rose-600 transition hover:bg-rose-100 disabled:opacity-50"
    >
      <Trash2 className="h-3.5 w-3.5" />
      {disabled ? "삭제 중…" : "삭제"}
    </button>
  );
}
