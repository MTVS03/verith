import { Newspaper, TrendingUp, ExternalLink, ShieldCheck } from "lucide-react";

import type { NewsReportModel } from "@/types/news";
import { NewsSentimentBar } from "./news-sentiment-bar";
import { AnswerText } from "./answer-text";

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("ko-KR");
}

function DailyCounts({ report }: { report: NewsReportModel }) {
  const rows = report.daily_counts ?? [];
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <div className="flex items-end gap-2 pt-2" style={{ height: 140 }}>
      {rows.map((r) => (
        <div key={r.date} className="flex flex-1 flex-col items-center justify-end gap-1.5">
          <span className="text-[11px] font-semibold tabular-nums text-slate-400">{r.count}</span>
          <div
            className="w-full max-w-[36px] rounded-t-md bg-indigo-500/80"
            style={{ height: `${Math.round((r.count / max) * 100)}%`, minHeight: r.count ? 4 : 0 }}
          />
          <span className="text-[10px] text-slate-400">{r.date.slice(5)}</span>
        </div>
      ))}
    </div>
  );
}

export function NewsReportView({ report }: { report: NewsReportModel }) {
  return (
    <div className="flex flex-col gap-5">
      {/* Hero: 종합 감성 게이지 */}
      <section id="n-summary" className="rounded-2xl border border-[#e2e8f0] bg-white p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-[13px] font-bold text-indigo-600">
              <Newspaper className="h-4 w-4" /> 뉴스·심리 종합
            </div>
            <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">
              {report.subject}
            </h1>
            <p className="mt-1 text-[13px] text-slate-500">
              최근 {report.period_days}일 · 기준 {fmtDate(report.generated_at)}
              {report.data_limited ? " · 데이터 제한" : ""}
            </p>
          </div>
          <div className="rounded-xl bg-slate-50 px-4 py-2 text-right">
            <div className="text-[11px] font-bold text-slate-400">종합 감성</div>
            <div className="text-xl font-extrabold text-slate-900">{report.overall_gauge.label}</div>
            <div className="text-[11px] tabular-nums text-slate-400">
              score {report.overall_gauge.score.toFixed(2)}
            </div>
          </div>
        </div>
        <div className="mt-4">
          <NewsSentimentBar gauge={report.overall_gauge} />
        </div>
      </section>

      {/* AI 분석 (answer_text) */}
      <section id="n-answer" className="rounded-2xl border border-[#e2e8f0] bg-white p-6">
        <h2 className="text-[15px] font-bold text-slate-900">AI 분석</h2>
        <div className="mt-3">
          <AnswerText text={report.answer_text} />
        </div>
        {report.note ? <p className="mt-3 text-[12px] text-slate-400">{report.note}</p> : null}
      </section>

      {/* 일자별 기사량 */}
      <section id="n-volume" className="rounded-2xl border border-[#e2e8f0] bg-white p-6">
        <h2 className="text-[15px] font-bold text-slate-900">일자별 기사량</h2>
        <p className="mt-0.5 text-[12.5px] text-slate-500">최근 {report.period_days}일 수집 기사 수</p>
        <DailyCounts report={report} />
      </section>

      {/* 주요 이슈 (top_events) */}
      <section id="n-events" className="rounded-2xl border border-[#e2e8f0] bg-white p-6">
        <h2 className="text-[15px] font-bold text-slate-900">
          주요 이슈 <span className="text-slate-400">({report.top_events.length})</span>
        </h2>
        <div className="mt-4 flex flex-col gap-3">
          {report.top_events.map((ev) => (
            <details key={ev.canonical_id} className="group rounded-xl border border-slate-100 bg-slate-50/60 p-4">
              <summary className="flex cursor-pointer list-none items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-[11px] font-bold text-slate-400">
                    <TrendingUp className="h-3.5 w-3.5" />
                    중요도 {ev.importance.toFixed(2)} · 기사 {ev.article_count}건
                  </div>
                  <div className="mt-1 text-[14.5px] font-bold leading-snug text-slate-800">
                    {ev.canonical_title}
                  </div>
                </div>
                <span className="shrink-0 rounded-lg bg-white px-2.5 py-1 text-[11px] font-bold text-slate-600 ring-1 ring-slate-200">
                  {ev.gauge.label}
                </span>
              </summary>
              <div className="mt-3">
                <NewsSentimentBar gauge={ev.gauge} size="sm" />
              </div>
              <ul className="mt-3 flex flex-col gap-2">
                {ev.articles.slice(0, 6).map((a) => (
                  <li key={a.news_id} className="rounded-lg bg-white p-3 ring-1 ring-slate-100">
                    <a
                      href={a.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 text-[13px] font-bold text-slate-800 hover:text-indigo-600"
                    >
                      {a.title}
                      <ExternalLink className="h-3 w-3 shrink-0 text-slate-400" />
                    </a>
                    {a.summary ? (
                      <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-slate-500">
                        {a.summary}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </div>
      </section>

      {/* 근거 요약 */}
      <section id="n-evidence" className="rounded-2xl border border-[#e2e8f0] bg-white p-6">
        <h2 className="text-[15px] font-bold text-slate-900">근거</h2>
        <div className="mt-3 flex flex-wrap gap-3 text-[13px]">
          <span className="rounded-lg bg-slate-50 px-3 py-2 font-semibold text-slate-600">
            인용 이벤트 <b className="text-slate-900">{report.cited_event_ids.length}</b>건
          </span>
          <span className="rounded-lg bg-slate-50 px-3 py-2 font-semibold text-slate-600">
            근거 기사 <b className="text-slate-900">{report.evidence_news_ids.length}</b>건
          </span>
        </div>
      </section>

      <div className="flex items-center gap-2.5 rounded-2xl border border-[#f1f5f9] bg-[#f8fafc] p-4">
        <ShieldCheck className="h-5 w-5 shrink-0 text-emerald-500" />
        <p className="text-[13px] text-slate-500">
          이 리포트는 뉴스·감성 종합이며 <b className="font-semibold text-slate-900">투자 권유가 아닙니다.</b> 모든 감성 수치는 수집 기사에 연결되어 검증됩니다.
        </p>
      </div>
    </div>
  );
}
