"use client";

import { useCallback, useEffect, useState } from "react";
import { technicalReportsApi } from "@/lib/api/technical-reports";
import { toApiError, type ApiError } from "@/lib/api/client";
import type { TechnicalReportReadModel } from "@/types/technical-report";

interface State {
  report: TechnicalReportReadModel | null;
  loading: boolean;
  error: ApiError | null;
}

/** technical 리포트 단건 조회 훅(상세 화면용). */
export function useTechnicalReport(reportId: string) {
  const [state, setState] = useState<State>({
    report: null,
    loading: true,
    error: null,
  });

  // 초기/재조회 로드는 effect 안에서 promise 로 처리하고 setState 는 await 이후(비동기 콜백)에서만 한다
  // — effect 본문에서 동기 setState 를 피한다(react-hooks/set-state-in-effect).
  useEffect(() => {
    let alive = true;
    technicalReportsApi
      .get(reportId)
      .then((report) => {
        if (alive) setState({ report, loading: false, error: null });
      })
      .catch((err) => {
        if (alive) setState({ report: null, loading: false, error: toApiError(err) });
      });
    return () => {
      alive = false;
    };
  }, [reportId]);

  // 재시도(사용자 이벤트) — 이벤트 핸들러에서의 setState 는 허용된다.
  const reload = useCallback(() => {
    setState({ report: null, loading: true, error: null });
    technicalReportsApi
      .get(reportId)
      .then((report) => setState({ report, loading: false, error: null }))
      .catch((err) =>
        setState({ report: null, loading: false, error: toApiError(err) }),
      );
  }, [reportId]);

  return { ...state, reload };
}
