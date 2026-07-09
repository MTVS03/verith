"use client";

import Link from "next/link";
import { ChevronLeft, Newspaper, ShieldAlert } from "lucide-react";
import { useNewsReport } from "@/lib/hooks/useNewsReport";
import { formatDate } from "@/utils/format";
import { cn } from "@/lib/cn";
import type {
  NewsReportModel,
  ReportEvent,
  SentimentGauge,
} from "@/types/news-report";

/** 감성 순점수(score) 부호별 색. */
function scoreColor(score: number): string {
  if (score > 0) return "text-emerald-600";
  if (score < 0) return "text-rose-500";
  return "text-slate-500";
}

/** 게이지 라벨 → 톤 색(pill). */
function labelClass(label: string): string {
  if (label === "대체로 긍정") return "text-emerald-600 bg-emerald-50 border-emerald-100";
  if (label === "대체로 부정") return "text-rose-600 bg-rose-50 border-rose-100";
  if (label === "데이터 제한") return "text-slate-500 bg-slate-100 border-slate-200";
  return "text-amber-600 bg-amber-50 border-amber-100";
}

/** 긍/중/부 3분할 게이지 바 — 주어진 % 로 width 만 그린다(계산 없음). */
function GaugeBar({ g, className }: { g: SentimentGauge; className?: string }) {
  return (
    <div
      className={cn(
        "h-3 rounded-full overflow-hidden flex bg-slate-100",
        className,
      )}
    >
      <span style={{ width: `${g.positive_pct}%` }} className="bg-emerald-500" />
      <span style={{ width: `${g.neutral_pct}%` }} className="bg-slate-300" />
      <span style={{ width: `${g.negative_pct}%` }} className="bg-rose-500" />
    </div>
  );
}

/** 날짜별 뉴스량 막대(간단) — backend 가 준 count 로 높이만 그린다. */
function DailyCounts({ report }: { report: NewsReportModel }) {
  const data = report.daily_counts;
  if (!data.length) return null;
  const max = Math.max(...data.map((d) => d.count), 1);
  return (
    <div>
      <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">
        날짜별 뉴스량
      </div>
      <div className="flex items-end gap-1.5 h-24">
        {data.map((d) => (
          <div key={d.date} className="flex-1 flex flex-col items-center gap-1 min-w-0">
            <div className="w-full flex items-end justify-center h-20">
              <div
                className="w-full max-w-[22px] bg-indigo-500/80 rounded-t"
                style={{ height: `${Math.max((d.count / max) * 100, 4)}%` }}
                title={`${d.date} · ${d.count}건`}
              />
            </div>
            <span className="text-[9px] text-slate-400 num truncate w-full text-center">
              {d.date.slice(5)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function IssueRow({ ev, rank }: { ev: ReportEvent; rank: number }) {
  return (
    <div
      id={`issue-${rank}`}
      className="scroll-mt-6 border border-slate-200/80 bg-white rounded-2xl p-4"
    >
      <div className="flex items-start gap-4">
        <div
          className={cn(
            "w-8 text-center text-lg font-extrabold num shrink-0",
            rank <= 3 ? "text-indigo-600" : "text-slate-300",
          )}
        >
          {rank}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-[15px] font-bold text-slate-900">
              {ev.canonical_title}
            </h3>
            <span
              className={cn(
                "inline-flex items-center text-[11px] font-semibold border rounded-full px-2 py-0.5",
                labelClass(ev.gauge.label),
              )}
            >
              {ev.gauge.label}
            </span>
            <span className="text-[12px] text-slate-400">
              기사 <b className="num text-slate-600">{ev.article_count}</b>건 · 중요도{" "}
              <span className="num">{ev.importance.toFixed(1)}</span>
            </span>
          </div>

          <div className="flex items-center gap-3 mt-3">
            <GaugeBar g={ev.gauge} className="flex-1" />
            <div className="text-[11.5px] font-medium num shrink-0">
              <span className="text-emerald-600">긍 {ev.gauge.positive}</span>{" "}
              <span className="text-slate-400">중 {ev.gauge.neutral}</span>{" "}
              <span className="text-rose-500">부 {ev.gauge.negative}</span>
            </div>
          </div>

          {ev.articles.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {ev.articles.map((a) => (
                <li key={a.news_id} className="text-[12.5px] text-slate-500">
                  ·{" "}
                  <a
                    href={a.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-slate-700 hover:text-indigo-600 transition"
                  >
                    {a.summary}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

export function NewsReportBody({ report }: { report: NewsReportModel }) {
  const g = report.overall_gauge;
  // 근거 이슈 칩 — cited_event_ids ∈ top_events(canonical_id) 매칭(순위 부여).
  const chips = report.top_events
    .map((ev, i) => ({ rank: i + 1, title: ev.canonical_title, id: ev.canonical_id }))
    .filter((c) => c.id && report.cited_event_ids.includes(c.id));

  return (
    <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card overflow-hidden">
      {/* HERO */}
      <header className="p-8 pb-6">
        <span className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-indigo-700 bg-indigo-50 rounded-full px-2.5 py-1">
          <Newspaper className="w-3.5 h-3.5" /> News · Sentiment
        </span>
        <h1 className="text-3xl font-bold text-slate-900 mt-3 tracking-tight leading-tight">
          {report.subject} <span className="text-slate-300 font-medium">·</span> 최근 뉴스 여론
        </h1>
        <p className="text-[13px] text-slate-500 mt-2">
          {report.period_days ? `최근 ${report.period_days}일 집계 · ` : ""}
          <span className="num">{formatDate(report.generated_at)}</span> 업데이트
          {g.total > 0 && (
            <>
              {" "}
              · 분석 기사 <b className="num text-slate-700">{g.total}</b>건
            </>
          )}
        </p>
      </header>

      {report.data_limited && (
        <div className="mx-8 mb-2 p-3.5 rounded-xl bg-amber-50 border border-amber-200 text-amber-800 text-[13px] flex gap-2.5 items-start">
          <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <b>데이터 제한</b> — {report.note ?? "근거가 부족한 부분은 추정으로 채우지 않습니다."}
          </div>
        </div>
      )}

      {/* SENTIMENT OVERVIEW */}
      <section className="p-8 border-t border-slate-100 grid md:grid-cols-[300px_1fr] gap-8 items-center">
        <div>
          <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
            전체 감성
          </div>
          <div className={cn("text-[40px] font-bold leading-none mt-1 num", scoreColor(g.score))}>
            {g.score > 0 ? "+" : ""}
            {g.score.toFixed(2)}
          </div>
          <GaugeBar g={g} className="mt-3.5" />
          <div className="flex gap-4 text-[12px] font-medium mt-2 num">
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />긍정 {g.positive_pct}%
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-slate-300" />중립 {g.neutral_pct}%
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />부정 {g.negative_pct}%
            </span>
          </div>
        </div>
        <div className="border border-slate-200/80 rounded-2xl p-5">
          <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
            분석 기사 수
          </div>
          <div className="text-[34px] font-bold text-slate-900 leading-none mt-2 num">
            {g.total}
            <span className="text-[15px] text-slate-400 font-medium"> 건</span>
          </div>
          <div className="text-[12.5px] text-slate-400 mt-2">중복 제거 후 감성 집계 대상</div>
        </div>
      </section>

      {/* DAILY COUNTS */}
      {report.daily_counts.length > 0 && (
        <section className="px-8 pb-8">
          <DailyCounts report={report} />
        </section>
      )}

      {/* NEWS FLOW SUMMARY */}
      <section className="p-8 border-t border-slate-100 bg-slate-50/60">
        <h2 className="text-base font-bold text-slate-900 mb-4">뉴스 흐름 요약</h2>
        <div className="bg-white border border-slate-200/80 rounded-2xl p-5">
          {report.answer_text ? (
            <p className="text-[14.5px] text-slate-700 leading-[1.8] whitespace-pre-line">
              {report.answer_text}
            </p>
          ) : (
            <p className="text-[13px] text-slate-400">요약할 내용이 없습니다 (데이터 제한).</p>
          )}
          {chips.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap mt-4 pt-3.5 border-t border-slate-100">
              <span className="text-[11px] font-semibold text-slate-400">근거 이슈</span>
              {chips.map((c) => (
                <a
                  key={c.rank}
                  href={`#issue-${c.rank}`}
                  className="text-[12px] font-medium text-slate-700 bg-slate-50 border border-slate-200 rounded-full px-2.5 py-1 hover:border-indigo-300 hover:text-indigo-600 transition"
                >
                  #{c.rank} {c.title}
                </a>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* TOP ISSUES */}
      <section className="p-8 border-t border-slate-100">
        <h2 className="text-base font-bold text-slate-900">
          주요 이슈 TOP {report.top_events.length}
        </h2>
        <p className="text-[12.5px] text-slate-400 mt-1.5 mb-4">
          중요도(importance) 순 · 감성은 단정하지 않고 분포로 표시합니다.
        </p>
        {report.top_events.length > 0 ? (
          <div className="space-y-2.5">
            {report.top_events.map((ev, i) => (
              <IssueRow key={ev.canonical_id ?? i} ev={ev} rank={i + 1} />
            ))}
          </div>
        ) : (
          <p className="text-[12.5px] text-slate-400">표시할 이슈가 없습니다 (데이터 제한).</p>
        )}
      </section>

      <footer className="px-8 py-5 border-t border-slate-100 text-[12.5px] text-slate-500">
        이 데이터는 뉴스 여론 요약이며 <b>투자 권유가 아닙니다</b>. 모든 수치는 출처 기사에 연결되어
        검증됩니다.
      </footer>
    </div>
  );
}

export function NewsReportView({ reportId }: { reportId: string }) {
  const { report, loading, error, reload } = useNewsReport(reportId);

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-8 max-w-4xl mx-auto space-y-6 screen-enter">
        <Link
          href="/library"
          className="inline-flex items-center gap-1.5 text-xs font-bold text-indigo-600 hover:text-indigo-800 transition"
        >
          <ChevronLeft className="w-4 h-4" /> 보관함으로 돌아가기
        </Link>

        {loading && (
          <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-8 h-96 animate-pulse" />
        )}

        {!loading && error && (
          <div className="py-16 bg-white border border-dashed border-rose-200 rounded-2xl text-center">
            <p className="text-xs font-semibold text-rose-500">
              {error.kind === "not_found"
                ? "리포트를 찾을 수 없습니다."
                : "리포트를 불러오지 못했습니다."}
            </p>
            {error.kind !== "not_found" && (
              <button
                onClick={reload}
                className="mt-3 text-xs font-bold text-indigo-600 hover:text-indigo-800 transition"
              >
                다시 시도
              </button>
            )}
          </div>
        )}

        {!loading && !error && report && <NewsReportBody report={report} />}
      </div>
    </div>
  );
}
