"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { GitBranch, Sparkles } from "lucide-react";

import { analyzeQuery } from "@/api/supervisor";
import { createTechnicalReport } from "@/api/technical-create";
import type { SupervisorAnalyzeResponse } from "@/types/supervisor";
import { AGENT_META, AGENT_ORDER } from "@/features/supervisor/lib/agents";
import { PipelineBox, type PipelineStep, type StepState } from "./pipeline-box";
import { Composer } from "./composer";
import { ResultMessage } from "./result-message";

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
  // technical 만 실제 저장까지 연결 — 파이프라인이 backend create 로 진짜 리포트를 만든다.
  const [technicalReportId, setTechnicalReportId] = useState<string | null>(null);
  const [technicalCreating, setTechnicalCreating] = useState(false);
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
      setTechnicalReportId(null);
      setTechnicalCreating(false);
      setPhase("running");

      const { response: res, live: isLive } = await analyzeQuery(q);
      setResponse(res);
      setLive(isLive);

      // technical 이 성공하고 종목이 확정되면, 실제 저장까지 연결한다(backend create → report_id).
      // 애니메이션과 병렬로 진행 — 사용자가 결과를 읽는 동안 버튼이 활성화된다.
      const stock = res.resolution.stock;
      const techOk = res.results.find((r) => r.agent_type === "technical")?.status === "success";
      if (stock && techOk) {
        setTechnicalCreating(true);
        createTechnicalReport({ ticker: stock.stock_code, query: q })
          .then((r) => setTechnicalReportId(r.report_id))
          .catch(() => setTechnicalReportId(null))
          .finally(() => setTechnicalCreating(false));
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
                  <ResultMessage
                    response={response}
                    technicalReportId={technicalReportId}
                    technicalCreating={technicalCreating}
                  />
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
