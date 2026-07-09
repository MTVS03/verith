"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { FileText, Plus, Search, SearchX, ShieldCheck } from "lucide-react";
import { useArchive } from "@/lib/hooks/useArchive";
import { StatusBadge, type BadgeTone } from "@/components/common/StatusBadge";
import { AGENT_TYPE_LABELS, REGIME_LABELS, labelOf } from "@/constants/labels";
import { cn } from "@/lib/cn";
import type { ArchiveItem } from "@/types/report-archive";

/** 상단 필터: 전체 + 도메인(agent_type). undefined = 전체. */
const FILTERS: { label: string; agentType?: string }[] = [
  { label: "전체", agentType: undefined },
  { label: AGENT_TYPE_LABELS.technical, agentType: "technical" },
  { label: AGENT_TYPE_LABELS.fundamental, agentType: "fundamental" },
  { label: AGENT_TYPE_LABELS.news, agentType: "news" },
];

/** archive badge_tone(green/amber/red/neutral) → StatusBadge tone. */
function toneOf(tone: string | null): BadgeTone {
  switch (tone) {
    case "green":
      return "verified";
    case "red":
      return "negative";
    case "amber":
      return "warning";
    default:
      return "neutral";
  }
}

/** 프론트 상세 라우트 — agent_type + report_id 로 구성. */
function detailRoute(item: ArchiveItem): string {
  return `/reports/${item.agent_type}/${item.report_id}`;
}

function ReportCard({ item }: { item: ArchiveItem }) {
  const { card, stock } = item;
  return (
    <Link
      href={detailRoute(item)}
      className="group bg-white rounded-2xl border border-slate-200/80 shadow-card hover:shadow-pop hover:-translate-y-0.5 transition-all duration-300 p-5 flex flex-col justify-between min-h-[175px]"
    >
      <div>
        <div className="flex items-start justify-between">
          <span className="w-10 h-10 rounded-xl bg-indigo-50 border border-indigo-100/50 text-indigo-600 grid place-items-center">
            <FileText className="w-5 h-5" />
          </span>
          {card.badge_value && (
            <StatusBadge
              tone={toneOf(card.badge_tone)}
              icon={<ShieldCheck className="w-3 h-3" />}
              label={`${card.badge_label ?? "Conf"} ${card.badge_value}`}
            />
          )}
        </div>
        <h3 className="font-bold text-slate-800 text-[14.5px] mt-4 leading-snug group-hover:text-indigo-600 transition-colors duration-200 line-clamp-2">
          {card.title}
        </h3>
        <div className="flex items-center gap-2 mt-2 text-[11px] text-slate-400 font-medium">
          <span className="text-slate-600">{stock.stock_name ?? stock.stock_code}</span>
          <span>·</span>
          <span>{labelOf(AGENT_TYPE_LABELS, item.agent_type)}</span>
        </div>
      </div>
      <div className="flex items-center justify-between mt-5 pt-3.5 border-t border-slate-100 text-[11px] text-slate-400">
        <span className="font-medium">
          {card.meta_primary ? labelOf(REGIME_LABELS, card.meta_primary) : ""}
        </span>
        <span className="num">{card.meta_secondary ?? ""}</span>
      </div>
    </Link>
  );
}

export function LibraryScreen() {
  const [agentType, setAgentType] = useState<string | undefined>(undefined);
  const [keyword, setKeyword] = useState("");
  const { items, loading, error, reload } = useArchive(agentType);

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return items;
    return items.filter((i) => {
      const t = i.card.title?.toLowerCase() ?? "";
      const n = i.stock.stock_name?.toLowerCase() ?? "";
      return t.includes(kw) || n.includes(kw);
    });
  }, [items, keyword]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-8 max-w-6xl mx-auto space-y-6 screen-enter">
        {/* 헤더 */}
        <div className="flex items-end justify-between flex-wrap gap-4">
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">
              리포트 보관함
            </h1>
            <p className="text-slate-500 text-xs mt-1.5">
              검증 게이트를 통과해 저장된 출처 표기 리포트 목록입니다.
            </p>
          </div>
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold rounded-xl shadow-md transition"
          >
            <Plus className="w-4 h-4" /> 새 리포트 생성
          </Link>
        </div>

        {/* 필터 + 검색 */}
        <div className="flex items-center justify-between flex-wrap gap-4 pt-2">
          <div className="flex gap-2 flex-wrap">
            {FILTERS.map((f) => {
              const active = agentType === f.agentType;
              return (
                <button
                  key={f.label}
                  onClick={() => setAgentType(f.agentType)}
                  className={cn(
                    "px-4 py-2 rounded-xl text-xs font-bold transition-all",
                    active
                      ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/10"
                      : "bg-white border border-slate-200 text-slate-600 hover:border-slate-300",
                  )}
                >
                  {f.label}
                </button>
              );
            })}
          </div>

          <div className="relative w-64">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">
              <Search className="w-4 h-4" />
            </span>
            <input
              type="text"
              placeholder="종목 또는 키워드 검색..."
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-white border border-slate-200 hover:border-slate-300 focus:border-indigo-400 focus:outline-none rounded-xl text-xs text-slate-800 transition"
            />
          </div>
        </div>

        {/* 상태별 렌더 */}
        {loading && (
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5 pt-1">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-5 min-h-[175px] animate-pulse"
              >
                <div className="w-10 h-10 rounded-xl bg-slate-100" />
                <div className="h-4 bg-slate-100 rounded mt-4 w-3/4" />
                <div className="h-3 bg-slate-100 rounded mt-2 w-1/2" />
              </div>
            ))}
          </div>
        )}

        {!loading && error && (
          <div className="py-16 bg-white border border-dashed border-rose-200 rounded-2xl text-center">
            <p className="text-xs font-semibold text-rose-500">
              보관함을 불러오지 못했습니다.
            </p>
            <button
              onClick={reload}
              className="mt-3 text-xs font-bold text-indigo-600 hover:text-indigo-800 transition"
            >
              다시 시도
            </button>
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="py-16 bg-white border border-dashed border-slate-200 rounded-2xl text-center">
            <div className="w-12 h-12 bg-slate-50 border border-slate-100 text-slate-300 grid place-items-center rounded-xl mx-auto mb-3">
              <SearchX className="w-6 h-6" />
            </div>
            <p className="text-xs font-semibold text-slate-500">
              {keyword ? "검색 조건에 맞는 리포트가 없습니다." : "저장된 리포트가 아직 없습니다."}
            </p>
          </div>
        )}

        {!loading && !error && filtered.length > 0 && (
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5 pt-1">
            {filtered.map((item) => (
              <ReportCard key={item.report_id} item={item} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
