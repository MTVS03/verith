import type { NextConfig } from "next";

/**
 * 백엔드 프록시.
 * 브라우저는 same-origin `/api/*` 로 호출하고, Next 가 이를 백엔드로 프록시한다.
 * 이렇게 하면 CORS 설정 없이(백엔드 무수정) 브라우저 → 백엔드 연동이 된다.
 *
 * 대상 백엔드 주소는 BACKEND_API_URL(서버 전용) 또는 NEXT_PUBLIC_API_URL 로 정한다.
 */
const BACKEND_API_URL =
  process.env.BACKEND_API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

// 슈퍼바이저는 AI 서비스(내부 endpoint)에 있다. 지금은 프론트가 프록시로 직접 호출한다
// (백엔드에 supervisor 전달 라우트가 생기면 이 대상만 백엔드로 바꾼다).
const AI_SERVICE_URL = process.env.AI_SERVICE_URL ?? "http://localhost:9000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_API_URL}/api/:path*`,
      },
      {
        // 뉴스 라우터는 백엔드에서 /news prefix 를 쓴다(/api 아님).
        source: "/news/:path*",
        destination: `${BACKEND_API_URL}/news/:path*`,
      },
      {
        // 슈퍼바이저(및 기타 AI internal endpoint) — AI 서비스로 프록시.
        source: "/internal/:path*",
        destination: `${AI_SERVICE_URL}/internal/:path*`,
      },
    ];
  },
};

export default nextConfig;
