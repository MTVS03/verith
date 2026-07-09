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
  "http://127.0.0.1:8000";

// 프론트가 붙는 곳은 백엔드(:8000) 하나뿐이다. 슈퍼바이저(AI 서비스)는 백엔드가 대신 호출한다
// (POST /api/research → 백엔드 → /internal/supervisor/analyze). 프론트는 AI 를 직접 호출하지 않는다.
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
    ];
  },
};

export default nextConfig;
