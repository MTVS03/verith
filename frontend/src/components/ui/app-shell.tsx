import Link from "next/link";
import type { ReactNode } from "react";

export function AppShell({
  children,
  title = "veriθ",
  subtitle,
}: {
  children: ReactNode;
  title?: string;
  subtitle?: string;
}) {
  return (
    <div className="min-h-screen bg-[linear-gradient(180deg,#f8fafc_0%,#eef2ff_100%)] text-slate-900">
      <header className="border-b border-white/60 bg-white/75 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4 lg:px-8">
          <Link href="/" className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-2xl bg-indigo-600 text-lg font-semibold text-white shadow-lg shadow-indigo-500/20">
              θ
            </div>
            <div>
              <p className="text-sm font-semibold tracking-[0.16em] text-indigo-600 uppercase">
                veriθ
              </p>
              <p className="text-xs text-slate-500">Evidence-based AI Stock Research</p>
            </div>
          </Link>
          <Link
            href="/research"
            className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-md shadow-indigo-500/20 transition hover:bg-indigo-700"
          >
            AI 리서치
          </Link>
        </div>
      </header>

      <main className="mx-auto flex max-w-7xl flex-col gap-8 px-6 py-8 lg:px-8">
        <div className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight text-slate-950">{title}</h1>
          {subtitle ? <p className="text-sm text-slate-500">{subtitle}</p> : null}
        </div>
        {children}
      </main>
    </div>
  );
}
