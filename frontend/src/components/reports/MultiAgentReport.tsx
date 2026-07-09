"use client";

import { useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/cn";
import { AgentHtmlReport } from "./AgentHtmlReport";
import { NewsReportBody } from "./news/NewsReportView";
import { TechnicalAgentReport } from "./technical/TechnicalAgentReport";
import type { AgentResult, AgentType, SupervisorResponse } from "@/types/supervisor";
import type { NewsReportModel } from "@/types/news-report";
import type { TechnicalAgentOutput } from "@/types/technical-agent-output";

/** 탭 표시 순서 + 라벨. */
const AGENT_ORDER: AgentType[] = [
  "technical",
  "fundamental",
  "news",
  "flow",
  "industry",
];
const AGENT_TAB_LABELS: Record<AgentType, string> = {
  technical: "가격/기술",
  fundamental: "재무/펀더멘탈",
  news: "뉴스/심리",
  flow: "수급",
  industry: "산업/거시",
};

/** 실패/데이터 없음 카드. */
function AgentUnavailable({ result }: { result: AgentResult }) {
  return (
    <div className="py-16 bg-white border border-dashed border-slate-200 rounded-2xl text-center">
      <div className="w-12 h-12 bg-amber-50 border border-amber-100 text-amber-500 grid place-items-center rounded-xl mx-auto mb-3">
        <AlertTriangle className="w-6 h-6" />
      </div>
      <p className="text-xs font-semibold text-slate-500">
        이 에이전트의 리포트를 생성하지 못했습니다.
      </p>
      {result.reason && (
        <p className="text-[10.5px] text-slate-400 mt-1">사유: {result.reason}</p>
      )}
    </div>
  );
}

/** agent_type 별로 알맞은 렌더러로 분기. HTML 을 주는 에이전트는 그대로 주입한다. */
function AgentReportBody({ result }: { result: AgentResult }) {
  if (result.status !== "success" || result.output == null) {
    return <AgentUnavailable result={result} />;
  }
  const output = result.output as Record<string, unknown>;

  // flow / fundamental: 완성 HTML 을 그대로 표시
  const html = (output.html ?? output.report_html) as string | undefined;
  if (typeof html === "string" && html.trim()) {
    return <AgentHtmlReport html={html} />;
  }

  if (result.agent_type === "news") {
    return <NewsReportBody report={result.output as NewsReportModel} />;
  }
  if (result.agent_type === "technical") {
    return <TechnicalAgentReport output={result.output as TechnicalAgentOutput} />;
  }

  // 구조화 출력이지만 전용 렌더러가 없는 경우(안전 착지)
  return <AgentUnavailable result={result} />;
}

export function MultiAgentReport({ response }: { response: SupervisorResponse }) {
  // 응답 순서를 고정 순서로 정렬(없는 에이전트는 제외).
  const results = useMemo(() => {
    const byType = new Map(response.results.map((r) => [r.agent_type, r]));
    return AGENT_ORDER.map((t) => byType.get(t)).filter(
      (r): r is AgentResult => Boolean(r),
    );
  }, [response.results]);

  const [active, setActive] = useState<AgentType>(
    () => results.find((r) => r.status === "success")?.agent_type ?? results[0]?.agent_type ?? "technical",
  );

  const activeResult = results.find((r) => r.agent_type === active);

  return (
    <div className="space-y-4">
      {/* 탭 */}
      <div className="flex gap-1.5 flex-wrap border-b border-slate-200 pb-3">
        {results.map((r) => {
          const isActive = r.agent_type === active;
          const ok = r.status === "success" && r.output != null;
          return (
            <button
              key={r.agent_type}
              onClick={() => setActive(r.agent_type)}
              className={cn(
                "flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold transition",
                isActive
                  ? "bg-indigo-600 text-white shadow-md"
                  : "bg-white border border-slate-200 text-slate-600 hover:border-slate-300",
              )}
            >
              <span
                className={cn(
                  "w-1.5 h-1.5 rounded-full",
                  ok ? "bg-emerald-400" : "bg-slate-300",
                  isActive && ok && "bg-emerald-300",
                )}
              />
              {AGENT_TAB_LABELS[r.agent_type]}
            </button>
          );
        })}
      </div>

      {/* 활성 탭 리포트 */}
      {activeResult && <AgentReportBody result={activeResult} />}
    </div>
  );
}
