"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { GitBranch, Sparkles } from "lucide-react";

import { analyzeQuery } from "@/api/supervisor";
import { createTechnicalReport } from "@/api/technical-create";
import { createNewsReport } from "@/api/news-create";
import { createIndustryReport } from "@/api/industry-create";
import { createFundamentalReport } from "@/api/fundamental-create";
import { createFlowReport } from "@/api/flow-create";
import type { SupervisorAnalyzeResponse } from "@/types/supervisor";
import type { AgentType } from "@/types/archive";
import { AGENT_META, AGENT_ORDER } from "@/features/supervisor/lib/agents";
import { PipelineBox, type PipelineStep, type StepState } from "./pipeline-box";
import { Composer } from "./composer";
import { ResultMessage, type CreatedReports } from "./result-message";

type Phase = "intro" | "running" | "done";

// 스텝 = Planning(질문 해석·종목 resolve) + 5개 에이전트.
const PLANNING = {
  key: "planning",
  label: "Planning",
  desc: "Supervisor가 질문을 해석하고 종목을 확정하는 중...",
  icon: GitBranch,
};
const TOTAL_STEPS = 1 + AGENT_ORDER.length;

// 각 스텝의 "최종" 상태를 실제 supervisor 결과에서 뽑는다(연출이 아니라 진실).
function finalStateFor(idx: number, res: SupervisorAnalyzeResponse | null): StepState {
  if (!res) return "pending";
  if (idx === 0) return res.resolution.status === "resolved" ? "success" : "failed";
  const agent = AGENT_ORDER[idx - 1];
  const r = res.results.find((x) => x.agent_type === agent);
  return (r?.status as StepState) ?? "skipped";
}

function buildSteps(
  res: SupervisorAnalyzeResponse | null,
  stepsDone: number,
  phase: Phase,
): PipelineStep[] {
  return Array.from({ length: TOTAL_STEPS }, (_, idx) => {
    const meta = idx === 0 ? PLANNING : AGENT_META[AGENT_ORDER[idx - 1]];
    const key = idx === 0 ? "planning" : AGENT_ORDER[idx - 1];
    let state: StepState;
    if (phase === "done") {
      state = finalStateFor(idx, res);
    } else if (idx < stepsDone) {
      state = finalStateFor(idx, res);
    } else if (idx === stepsDone) {
      state = "active";
    } else {
      state = "pending";
    }
    return { key, label: meta.label, desc: meta.desc, icon: meta.icon, state };
  });
}

export function ResearchView() {
  const [phase, setPhase] = useState<Phase>("intro");
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<SupervisorAnalyzeResponse | null>(null);
  const [live, setLive] = useState(true);
  const [stepsDone, setStepsDone] = useState(0);
  // 실제 저장까지 연결된 리포트 — agent 별 {report_id, 생성중}. (technical·news)
  const [createdReports, setCreatedReports] = useState<CreatedReports>({});
  const timers = useRef<number[]>([]);

  const clearTimers = useCallback(() => {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
  }, []);

  useEffect(() => () => clearTimers(), [clearTimers]);

  const handleSubmit = useCallback(
    async (q: string) => {
      if (phase === "running") return;
      clearTimers();
      setQuery(q);
      setResponse(null);
      setStepsDone(0);
      setCreatedReports({});
      setPhase("running");

      const { response: res, live: isLive } = await analyzeQuery(q);
      setResponse(res);
      setLive(isLive);

      // 성공한 에이전트를 실제 저장까지 연결한다(→ report_id). 애니메이션과 병렬 —
      // 사용자가 결과를 읽는 동안 버튼이 활성화된다.
      const setCreated = (agent: AgentType, patch: { reportId?: string | null; creating?: boolean }) =>
        setCreatedReports((prev) => ({ ...prev, [agent]: { ...prev[agent], ...patch } }));
      const resultOf = (agent: AgentType) => res.results.find((r) => r.agent_type === agent);
      const stock = res.resolution.stock;

      // technical: backend create 가 AI 재호출→저장(입력은 ticker+query).
      if (stock && resultOf("technical")?.status === "success") {
        setCreated("technical", { creating: true, reportId: null });
        createTechnicalReport({ ticker: stock.stock_code, query: q })
          .then((r) => setCreated("technical", { reportId: r.report_id }))
          .catch(() => setCreated("technical", { reportId: null }))
          .finally(() => setCreated("technical", { creating: false }));
      }

      // fundamental: supervisor 가 이미 만든 output(FundamentalResponse)을 save-only 로 저장.
      // technical 처럼 backend 가 AI 를 재호출하지 않는다 — 중복 실행 제거(속도).
      const fundamentalResult = resultOf("fundamental");
      if (fundamentalResult?.status === "success" && fundamentalResult.output) {
        setCreated("fundamental", { creating: true, reportId: null });
        createFundamentalReport({ output: fundamentalResult.output, question: q })
          .then((r) => setCreated("fundamental", { reportId: r.report_id }))
          .catch(() => setCreated("fundamental", { reportId: null }))
          .finally(() => setCreated("fundamental", { creating: false }));
      }

      // flow: supervisor 가 이미 만든 output(AgentOutput{payload})을 save-only 로 저장.
      // flow 는 종목 의존 — 종목 확정 + 성공 + payload 가 있어야 저장한다.
      const flowResult = resultOf("flow");
      const flowPayload = flowResult?.output?.payload as Record<string, unknown> | undefined;
      if (stock && flowResult?.status === "success" && flowPayload) {
        setCreated("flow", { creating: true, reportId: null });
        createFlowReport({ payload: flowPayload, question: q })
          .then((r) => setCreated("flow", { reportId: r.report_id }))
          .catch(() => setCreated("flow", { reportId: null }))
          .finally(() => setCreated("flow", { creating: false }));
      }

      // news: supervisor 가 이미 만든 output(ReportModel)을 save-only 로 저장.
      const newsResult = resultOf("news");
      if (newsResult?.status === "success" && newsResult.output) {
        setCreated("news", { creating: true, reportId: null });
        createNewsReport({ report: newsResult.output, question: q })
          .then((r) => setCreated("news", { reportId: r.report_id }))
          .catch(() => setCreated("news", { reportId: null }))
          .finally(() => setCreated("news", { creating: false }));
      }

      // industry: backend create 가 AI(GraphRAG)를 재호출→검증→저장(입력은 원 질문).
      // supervisor 출력을 save-only 로 받는 경로가 없어 technical 과 동일 방식.
      if (resultOf("industry")?.status === "success") {
        setCreated("industry", { creating: true, reportId: null });
        createIndustryReport({ question: q })
          .then((r) => setCreated("industry", { reportId: r.report_id }))
          .catch(() => setCreated("industry", { reportId: null }))
          .finally(() => setCreated("industry", { creating: false }));
      }

      // 응답을 받은 뒤 스텝을 순차로 밝힌다(목업의 진행 연출과 동일 타이밍).
      let i = 0;
      const tick = () => {
        i += 1;
        setStepsDone(i);
        if (i >= TOTAL_STEPS) {
          setPhase("done");
          return;
        }
        timers.current.push(window.setTimeout(tick, 650 + Math.random() * 500));
      };
      timers.current.push(window.setTimeout(tick, 700));
    },
    [phase, clearTimers],
  );

  const percent =
    phase === "done" ? 100 : Math.min(Math.round(((stepsDone + 1) / TOTAL_STEPS) * 100), 100);
  const steps = buildSteps(response, stepsDone, phase);

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-slate-50">
      {/* 상단 브랜드 바 */}
      <header className="flex h-[60px] shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6">
        <Link href="/" className="flex items-center gap-2">
          <div className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-indigo-600 text-[17px] font-bold leading-none text-white">
            θ
          </div>
          <span className="text-[18px] font-bold tracking-tight text-slate-900">
            veri<span className="text-indigo-600">θ</span>
          </span>
          <span className="ml-1 rounded border border-slate-200 px-1.5 py-0.5 text-[9px] font-bold leading-none text-slate-400">
            BETA
          </span>
        </Link>
        <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
          AI 실시간 분석 리서치{phase === "done" && !live ? " · DEMO" : ""}
        </span>
      </header>

      {/* 대화/인트로 스크롤 영역 */}
      <div className="flex-1 overflow-y-auto px-8 py-8">
        {phase === "intro" ? (
          <div className="mx-auto flex min-h-[50vh] max-w-3xl flex-col items-center justify-center text-center">
            <div className="mb-6 grid h-16 w-16 place-items-center rounded-2xl border border-indigo-100 bg-indigo-50 text-indigo-600 shadow-md shadow-indigo-100">
              <Sparkles className="h-8 w-8" />
            </div>
            <h1 className="text-3xl font-extrabold leading-tight tracking-tight text-slate-900">
              근거 검증 기반 AI 리서치
            </h1>
            <p className="mt-3 max-w-lg text-sm leading-relaxed text-slate-500">
              원하시는 종목과 질문을 입력해 주세요. 5개 분석 에이전트(재무·기술·뉴스·수급·산업)가
              검증 게이트를 통과한 리포트를 생성합니다.
            </p>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-6">
            {/* 사용자 질문 말풍선 */}
            <div className="flex items-start justify-end gap-3">
              <div className="max-w-[80%] rounded-2xl rounded-tr-md bg-slate-900 px-5 py-3.5 text-[14.5px] leading-relaxed text-white shadow-md">
                {query}
              </div>
            </div>

            {/* AI 응답 */}
            <div className="flex gap-4">
              <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-indigo-600 text-sm font-bold text-white shadow-md">
                θ
              </div>
              <div className="flex-1 space-y-4">
                {phase === "running" ? (
                  <PipelineBox steps={steps} percent={percent} />
                ) : response ? (
                  <ResultMessage response={response} createdReports={createdReports} />
                ) : null}
              </div>
            </div>
          </div>
        )}
      </div>

      <Composer onSubmit={handleSubmit} disabled={phase === "running"} />
    </div>
  );
}
