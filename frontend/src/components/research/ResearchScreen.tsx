"use client";

import { AlertTriangle, Sparkles } from "lucide-react";
import { useResearchFlow } from "@/lib/hooks/useResearchFlow";
import { Composer } from "./Composer";
import { MultiAgentReport } from "@/components/reports/MultiAgentReport";
import type { ApiError } from "@/lib/api/client";

function errorMessage(err: ApiError | null): string {
  switch (err?.kind) {
    case "validation":
      return "질의 내용을 확인해 주세요. 종목명이나 6자리 코드를 포함해 다시 시도해 주세요.";
    case "upstream":
      return "분석 서버 응답에 문제가 있어 리포트를 완성하지 못했습니다. 잠시 후 다시 시도해 주세요.";
    case "unavailable":
      return "서비스가 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.";
    case "timeout":
      return "분석 생성이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.";
    case "network":
      return "서버에 연결할 수 없습니다. 백엔드/AI 서비스가 실행 중인지 확인해 주세요.";
    default:
      return "알 수 없는 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
  }
}

function AiAvatar() {
  return (
    <div className="w-9 h-9 rounded-xl bg-indigo-600 text-white font-bold grid place-items-center text-sm shadow-md shrink-0">
      θ
    </div>
  );
}

/** 진행 표시(정직) — 슈퍼바이저가 여러 서브에이전트를 실제로 돌리는 단일 왕복. */
function Analyzing() {
  return (
    <div className="bg-white rounded-2xl border border-slate-200/80 shadow-pop p-5 flex items-center gap-3">
      <span className="relative flex w-2 h-2">
        <span className="absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75 animate-ping" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-600" />
      </span>
      <div>
        <div className="text-[13.5px] font-bold text-slate-800">
          슈퍼바이저가 여러 에이전트로 분석 중
        </div>
        <div className="text-[11px] text-slate-400 mt-0.5">
          종목 확인 → 재무·기술·뉴스·수급·산업 에이전트 실행 (수십 초 소요될 수 있어요)
        </div>
      </div>
    </div>
  );
}

export function ResearchScreen() {
  const { state, submit } = useResearchFlow();
  const { phase } = state;
  const busy = phase === "analyzing";
  const isIntro = phase === "idle";
  const stockName = state.response?.resolution.stock?.stock_name;

  return (
    <div className="h-full flex flex-col screen-enter">
      <div className="flex-1 overflow-y-auto px-8 py-8">
        {isIntro ? (
          <div className="max-w-3xl mx-auto flex flex-col items-center justify-center min-h-[50vh] text-center">
            <div className="w-16 h-16 rounded-2xl bg-indigo-50 border border-indigo-100 text-indigo-600 grid place-items-center mb-6 shadow-md shadow-indigo-100">
              <Sparkles className="w-8 h-8" />
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 leading-tight">
              근거 검증 기반 AI 리서치
            </h1>
            <p className="text-slate-500 text-sm mt-3 max-w-lg leading-relaxed">
              종목과 질문을 자연어로 입력하면 슈퍼바이저가 재무·기술·뉴스·수급·산업 에이전트를 실행해
              검증된 리포트를 생성합니다.
            </p>
          </div>
        ) : (
          <div className="max-w-4xl mx-auto space-y-6">
            {/* 사용자 질의 */}
            <div className="flex justify-end items-start gap-3">
              <div className="bg-slate-900 text-white rounded-2xl rounded-tr-md px-5 py-3.5 max-w-[80%] text-[14.5px] leading-relaxed shadow-md">
                {state.query}
              </div>
            </div>

            {/* AI 응답 */}
            <div className="flex gap-4">
              <AiAvatar />
              <div className="flex-1 space-y-4 min-w-0">
                {busy && <Analyzing />}

                {phase === "done" && state.response && (
                  <>
                    {stockName && (
                      <div className="text-[13px] text-slate-500">
                        <b className="text-slate-800">{stockName}</b> 분석 결과입니다. 에이전트별
                        리포트를 확인하세요.
                      </div>
                    )}
                    <MultiAgentReport response={state.response} />
                  </>
                )}

                {phase === "error" && (
                  <div className="bg-white rounded-2xl border border-rose-200/80 shadow-md p-5 space-y-3">
                    <div className="flex items-center gap-2.5">
                      <span className="w-9 h-9 rounded-lg bg-rose-50 text-rose-500 grid place-items-center shrink-0">
                        <AlertTriangle className="w-5 h-5" />
                      </span>
                      <p className="text-[13.5px] font-bold text-slate-800">
                        리포트를 생성하지 못했습니다
                      </p>
                    </div>
                    <p className="text-xs text-slate-500 leading-relaxed">
                      {errorMessage(state.error)}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      <Composer onSubmit={submit} disabled={busy} />
    </div>
  );
}
