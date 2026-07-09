"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { Archive, Sparkles } from "lucide-react";
import { cn } from "@/lib/cn";

interface NavItem {
  href: string;
  label: string;
  icon: typeof Sparkles;
  /** active 판정: 정확히 일치하거나 이 prefix 로 시작 */
  match: (pathname: string) => boolean;
}

const NAV: NavItem[] = [
  {
    href: "/",
    label: "AI Research",
    icon: Sparkles,
    match: (p) => p === "/",
  },
  {
    href: "/library",
    label: "Library",
    icon: Archive,
    match: (p) => p === "/library" || p.startsWith("/reports"),
  },
];

/**
 * 앱 셸 — 상단 네비(로고 · 탭 · 컨텍스트 인디케이터) + 스크롤 가능한 메인 영역.
 * mockup 의 shell() 대응. header 는 고정 높이, main 만 스크롤한다.
 */
export function AppShell({
  children,
  contextLabel,
}: {
  children: ReactNode;
  contextLabel?: string;
}) {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-slate-50">
      <header className="h-16 shrink-0 bg-white border-b border-slate-200/80 flex items-center justify-between px-6 z-20 shadow-sm">
        <div className="flex items-center gap-8">
          {/* 로고 */}
          <Link
            href="/"
            className="flex items-center gap-2 cursor-pointer hover:opacity-80 transition"
          >
            <div className="w-8 h-8 rounded-lg bg-indigo-600 grid place-items-center text-white font-bold text-lg">
              θ
            </div>
            <span className="text-[19px] font-bold tracking-tight text-slate-900">
              veri<span className="text-indigo-600">θ</span>
            </span>
            <span className="ml-1 text-[9px] font-semibold text-slate-400 border border-slate-200 rounded px-1.5 py-0.5 leading-none">
              BETA
            </span>
          </Link>

          {/* 탭 */}
          <nav className="flex items-center gap-1.5">
            {NAV.map((item) => {
              const active = item.match(pathname);
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2 px-3.5 py-2.5 rounded-xl text-xs font-bold transition duration-150",
                    active
                      ? "bg-slate-100 text-indigo-600"
                      : "text-slate-500 hover:bg-slate-50 hover:text-slate-800",
                  )}
                >
                  <Icon className="w-3.5 h-3.5" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>
        </div>

        {/* 우측 컨텍스트 인디케이터 */}
        <div className="flex items-center gap-3">
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
            {contextLabel ?? ""}
          </span>
        </div>
      </header>

      <main className="flex-1 min-h-0 overflow-hidden bg-slate-50">
        {children}
      </main>
    </div>
  );
}
