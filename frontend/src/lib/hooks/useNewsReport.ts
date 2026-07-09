"use client";

import { useCallback, useEffect, useState } from "react";
import { newsReportsApi } from "@/lib/api/news-reports";
import { toApiError, type ApiError } from "@/lib/api/client";
import type { NewsReportModel } from "@/types/news-report";

interface State {
  report: NewsReportModel | null;
  loading: boolean;
  error: ApiError | null;
}

/** news 리포트 단건 조회 훅. envelope 에서 report(ReportModel)만 꺼내 반환. */
export function useNewsReport(reportId: string) {
  const [state, setState] = useState<State>({
    report: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let alive = true;
    newsReportsApi
      .get(reportId)
      .then((env) => {
        if (alive) setState({ report: env.report, loading: false, error: null });
      })
      .catch((err) => {
        if (alive) setState({ report: null, loading: false, error: toApiError(err) });
      });
    return () => {
      alive = false;
    };
  }, [reportId]);

  const reload = useCallback(() => {
    setState({ report: null, loading: true, error: null });
    newsReportsApi
      .get(reportId)
      .then((env) => setState({ report: env.report, loading: false, error: null }))
      .catch((err) =>
        setState({ report: null, loading: false, error: toApiError(err) }),
      );
  }, [reportId]);

  return { ...state, reload };
}
