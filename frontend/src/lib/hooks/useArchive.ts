"use client";

import { useCallback, useEffect, useState } from "react";
import { reportsApi } from "@/lib/api/reports";
import { toApiError, type ApiError } from "@/lib/api/client";
import type { ArchiveItem } from "@/types/report-archive";

interface ArchiveState {
  items: ArchiveItem[];
  total: number;
  loading: boolean;
  error: ApiError | null;
}

/**
 * 보관함 목록 조회 훅 — agent_type 필터 기준으로 서버에서 가져온다(created_at DESC).
 * 텍스트 검색은 화면(LibraryScreen)에서 로드된 목록에 클라이언트 필터로 적용한다.
 */
export function useArchive(agentType?: string) {
  const [state, setState] = useState<ArchiveState>({
    items: [],
    total: 0,
    loading: true,
    error: null,
  });

  // effect 본문에서 동기 setState 를 피한다 — setState 는 await 이후에만(react-hooks/set-state-in-effect).
  useEffect(() => {
    let alive = true;
    reportsApi
      .listArchive({ agent_type: agentType, limit: 50 })
      .then((res) => {
        if (alive)
          setState({
            items: res.items,
            total: res.total,
            loading: false,
            error: null,
          });
      })
      .catch((err) => {
        if (alive)
          setState((s) => ({ ...s, loading: false, error: toApiError(err) }));
      });
    return () => {
      alive = false;
    };
  }, [agentType]);

  // 재시도(사용자 이벤트) — 이벤트 핸들러에서의 setState 는 허용.
  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    reportsApi
      .listArchive({ agent_type: agentType, limit: 50 })
      .then((res) =>
        setState({
          items: res.items,
          total: res.total,
          loading: false,
          error: null,
        }),
      )
      .catch((err) =>
        setState((s) => ({ ...s, loading: false, error: toApiError(err) })),
      );
  }, [agentType]);

  return { ...state, reload };
}
