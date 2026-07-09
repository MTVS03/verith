"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";

import { deleteAllTechnicalReports } from "@/api/technical";
import { deleteAllNewsReports } from "@/api/news";
import { deleteAllIndustryReports } from "@/api/industry";
import { deleteAllFundamentalReports } from "@/api/fundamental";
import { deleteAllFlowReports } from "@/api/flow";
import type { AgentType } from "@/types/archive";

const LABEL: Record<AgentType, string> = {
  technical: "기술",
  fundamental: "재무",
  news: "뉴스",
  flow: "수급",
  industry: "산업",
};

async function deleteAllByType(agentType: AgentType): Promise<void> {
  if (agentType === "news") return void (await deleteAllNewsReports());
  if (agentType === "industry") return void (await deleteAllIndustryReports());
  if (agentType === "fundamental") return void (await deleteAllFundamentalReports());
  if (agentType === "flow") return void (await deleteAllFlowReports());
  await deleteAllTechnicalReports();
}

// 보관함 목록 **전체 삭제** 버튼(agent_type 별). 되돌릴 수 없는 대량 작업이라 확인을 강하게 받는다.
export function DeleteAllReportsButton({
  count,
  agentType = "technical",
}: {
  count: number;
  agentType?: AgentType;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);

  const onDeleteAll = async () => {
    if (busy || isPending) return;
    if (!window.confirm(`${LABEL[agentType]} 리포트 ${count}개를 모두 삭제할까요? 되돌릴 수 없습니다.`)) return;
    setBusy(true);
    try {
      await deleteAllByType(agentType);
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
