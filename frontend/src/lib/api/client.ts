/**
 * 백엔드 API client — axios 인스턴스 + 에러 정규화.
 * baseURL 은 public 환경변수만 사용(가이드라인 §2.2). 비밀값은 프론트 번들에 넣지 않는다.
 *
 * 컴포넌트는 fetch/axios 를 직접 호출하지 않고 도메인별 api 함수(stocks/technicalReports/reports)를 쓴다.
 */

import axios, { AxiosError } from "axios";

/**
 * 브라우저는 same-origin 상대경로(`/api/...`)로 호출하고, Next 의 rewrites 프록시가
 * 이를 백엔드로 전달한다(next.config.ts). 따라서 baseURL 은 비운다 — CORS 불필요.
 */
export const apiClient = axios.create({
  baseURL: "",
  timeout: 120_000, // AI 리포트 생성은 오래 걸릴 수 있다(504 전까지 대기).
  headers: { "Content-Type": "application/json" },
});

/** 정규화된 API 에러 종류 — 화면이 상태별로 분기하기 위한 최소 분류. */
export type ApiErrorKind =
  | "validation" // 422 입력 거부
  | "upstream" // 502 AI/업스트림 오류
  | "unavailable" // 503 일시적 사용 불가
  | "timeout" // 504 or 클라이언트 타임아웃
  | "not_found" // 404
  | "network" // 응답 없음(서버 미기동 등)
  | "unknown";

export class ApiError extends Error {
  kind: ApiErrorKind;
  status: number | null;
  detail: string | null;

  constructor(
    kind: ApiErrorKind,
    message: string,
    status: number | null = null,
    detail: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

/** axios 에러/기타 예외 → ApiError 로 정규화. */
export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;

  if (axios.isAxiosError(err)) {
    const ax = err as AxiosError<{ detail?: string }>;
    const status = ax.response?.status ?? null;
    const detail = ax.response?.data?.detail ?? null;

    if (ax.code === "ECONNABORTED") {
      return new ApiError("timeout", "요청 시간이 초과되었습니다.", status, detail);
    }
    if (!ax.response) {
      return new ApiError(
        "network",
        "서버에 연결할 수 없습니다.",
        null,
        ax.message,
      );
    }
    switch (status) {
      case 404:
        return new ApiError("not_found", "대상을 찾을 수 없습니다.", status, detail);
      case 422:
        return new ApiError("validation", "요청 내용을 확인해 주세요.", status, detail);
      case 502:
        return new ApiError("upstream", "분석 서버 응답에 문제가 있습니다.", status, detail);
      case 503:
        return new ApiError("unavailable", "일시적으로 사용할 수 없습니다.", status, detail);
      case 504:
        return new ApiError("timeout", "분석 생성이 지연되고 있습니다.", status, detail);
      default:
        return new ApiError("unknown", "알 수 없는 오류가 발생했습니다.", status, detail);
    }
  }

  return new ApiError("unknown", "알 수 없는 오류가 발생했습니다.");
}
