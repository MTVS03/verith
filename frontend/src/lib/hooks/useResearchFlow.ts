"use client";

import { useCallback, useState } from "react";
import { supervisorApi } from "@/lib/api/supervisor";
import { toApiError, type ApiError } from "@/lib/api/client";
import type { SupervisorResponse } from "@/types/supervisor";

/**
 * AI Research 상태 머신 — **자연어 한 번 → 슈퍼바이저 → 서브에이전트 리포트들**.
 *
 * 프론트는 종목 resolve·에이전트 라우팅을 직접 하지 않는다. 슈퍼바이저가 자연어를 받아
 * planning + execution 으로 각 서브에이전트를 돌리고, 그 리포트(JSON/HTML)를 돌려준다.
 * 프론트는 results[].output 을 에이전트별로 렌더만 한다.
 */
export type ResearchPhase = "idle" | "analyzing" | "done" | "error";

export interface ResearchState {
  phase: ResearchPhase;
  query: string;
  response: SupervisorResponse | null;
  error: ApiError | null;
}

const INITIAL: ResearchState = {
  phase: "idle",
  query: "",
  response: null,
  error: null,
};

export function useResearchFlow() {
  const [state, setState] = useState<ResearchState>(INITIAL);

  const submit = useCallback(async (rawQuery: string) => {
    const query = rawQuery.trim();
    if (!query) return;

    setState({ ...INITIAL, phase: "analyzing", query });
    try {
      const response = await supervisorApi.analyze(query);
      setState((s) => ({ ...s, phase: "done", response }));
    } catch (err) {
      setState((s) => ({ ...s, phase: "error", error: toApiError(err) }));
    }
  }, []);

  const reset = useCallback(() => setState(INITIAL), []);

  return { state, submit, reset };
}
