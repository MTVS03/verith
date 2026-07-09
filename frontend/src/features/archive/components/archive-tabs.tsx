"use client";

import Link from "next/link";

import clsx from "clsx";

import type { AgentType } from "@/types/archive";

const tabs: Array<{ key: AgentType; label: string }> = [
  { key: "technical", label: "기술" },
  { key: "fundamental", label: "재무" },
  { key: "news", label: "뉴스" },
  { key: "flow", label: "수급" },
  { key: "industry", label: "산업" },
];

export function ArchiveTabs({ active }: { active: AgentType }) {
  return (
    <div className="flex flex-wrap gap-2">
      {tabs.map((tab) => (
        <Link
          key={tab.key}
          href={`/?agent_type=${tab.key}`}
          className={clsx(
            "rounded-2xl border px-4 py-2 text-sm font-semibold transition",
            active === tab.key
              ? "border-indigo-600 bg-indigo-600 text-white shadow-md shadow-indigo-600/20"
              : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50",
          )}
        >
          {tab.label}
        </Link>
      ))}
    </div>
  );
}
