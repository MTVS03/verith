import type { Metadata } from "next";
import "./globals.css";
import { ToastProvider } from "@/components/common/Toast";

export const metadata: Metadata = {
  title: "veriθ — 근거 검증 기반 AI 리서치",
  description:
    "공시·뉴스·지표를 추적해 출처가 매핑된 검증 리포트를 생성하는 AI 주식 리서치 서비스",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="h-full antialiased">
      <head>
        {/* Pretendard 웹폰트 (동적 서브셋) — mockup 과 동일 소스 */}
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css"
        />
      </head>
      <body className="min-h-full flex flex-col bg-slate-50 text-slate-800">
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
