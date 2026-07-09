import Link from "next/link";
import { ShieldCheck, FileText, ArrowRight, Loader2 } from "lucide-react";

import type { SupervisorAnalyzeResponse } from "@/types/supervisor";
import { AGENT_META, AGENT_ORDER, agentReportHref } from "@/features/supervisor/lib/agents";

// 파이프라인 완료 후 AI 최종 메시지 + "리포트 열기" 버튼 (목업 ai-final-message).
// 목업은 전부 성공이었지만, 우리는 success 만 리포트 버튼으로 열고 failed/skipped 는
// 아래 상태 줄에 정직하게 표시한다(검증 가능성 = 이 프로젝트 정체성).
// technicalReportId: technical 만 실제 저장까지 연결돼 진짜 리포트를 연다(생성 중이면 로딩).
export function ResultMessage({
  response,
  technicalReportId = null,
  technicalCreating = false,
}: {
  response: SupervisorAnalyzeResponse;
  technicalReportId?: string | null;
  technicalCreating?: boolean;
}) {
  const stockName = response.resolution.stock?.stock_name ?? response.original_query;
  const byType = new Map(response.results.map((r) => [r.agent_type, r]));

  const succeeded = AGENT_ORDER.filter((t) => byType.get(t)?.status === "success");
  const failed = AGENT_ORDER.filter((t) => byType.get(t)?.status === "failed");
  const skipped = AGENT_ORDER.filter((t) => byType.get(t)?.status === "skipped");

  return (
    <div className="space-y-4 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-md">
      <p className="text-[14.5px] font-medium leading-relaxed text-slate-700">
        질문하신 <b className="font-bold text-slate-900">&ldquo;{stockName}&rdquo;</b> 분석 결과, 총{" "}
        <b className="font-bold text-indigo-600">{succeeded.length}개</b>의 에이전트가 검증 게이트를 통과해
        리포트를 생성했습니다.
      </p>

      <div className="flex flex-col gap-3 rounded-xl border border-emerald-100 bg-emerald-50/50 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-emerald-100 text-emerald-600">
            <ShieldCheck className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-xs font-bold text-emerald-800">검증 완료 리포트 구성 완료</div>
            <div className="mt-0.5 text-[10.5px] font-medium text-emerald-600">
              {succeeded.length}개 리포트 생성 · 종목 {response.resolution.stock?.stock_code ?? "-"}
              {response.resolution.stock?.market ? ` · ${response.resolution.stock.market}` : ""}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[10.5px] font-extrabold text-slate-500">리포트 열기:</span>
          {succeeded.map((type) => {
            const meta = AGENT_META[type];
            const Icon = meta.icon;

            // technical 은 실제 저장까지 연결됨 — 생성 중이면 로딩, 끝나면 진짜 리포트로.
            if (type === "technical" && technicalCreating && !technicalReportId) {
              return (
                <span
                  key={type}
                  className="inline-flex items-center gap-1 rounded-lg bg-indigo-100 px-2.5 py-1.5 text-[11px] font-bold text-indigo-500"
                >
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {meta.label} 저장 중
                </span>
              );
            }

            const reportId =
              type === "technical"
                ? technicalReportId
                : ((byType.get(type)?.output?.report_id as string | undefined) ?? null);
            const href = agentReportHref(type, reportId);
            const inner = (
              <>
                <Icon className="h-3.5 w-3.5" />
                {meta.label}
                {href ? <ArrowRight className="h-3 w-3" /> : null}
              </>
            );
            return href ? (
              <Link
                key={type}
                href={href}
                className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-2.5 py-1.5 text-[11px] font-bold text-white shadow-sm transition hover:bg-indigo-700"
              >
                {inner}
              </Link>
            ) : (
              <span
                key={type}
                title="상세 리포트 페이지 준비 중"
                className="inline-flex cursor-not-allowed items-center gap-1 rounded-lg bg-slate-100 px-2.5 py-1.5 text-[11px] font-bold text-slate-400"
              >
                {inner}
              </span>
            );
          })}
        </div>
      </div>

      {(failed.length > 0 || skipped.length > 0) && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-slate-100 pt-3 text-[11px] text-slate-400">
          <span className="flex items-center gap-1">
            <FileText className="h-3.5 w-3.5" />
            에이전트 상태
          </span>
          {failed.map((t) => (
            <span key={t} className="text-rose-500">
              {AGENT_META[t].label} 실패
            </span>
          ))}
          {skipped.map((t) => (
            <span key={t} className="text-slate-400">
              {AGENT_META[t].label} 건너뜀
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
