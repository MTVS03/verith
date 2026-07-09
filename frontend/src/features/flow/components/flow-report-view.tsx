import { Fragment } from "react";
import { ShieldCheck, ShieldAlert } from "lucide-react";

import type { FlowPayload } from "@/api/flow";

// flow 리포트를 payload(JSON)에서 그린다 — HTML 저장 안 함(storage-spec §0). 모든 숫자는 signals 에서.
// 순매수 금액은 백만원 단위 → 억원(÷100)으로 표시(flow 규약). 강도 ratio 는 하루평균 거래대금 대비 비율.

const INVESTORS = ["개인", "외국인", "기관"] as const;

function eok(millionWon: number | null | undefined): string {
  if (millionWon == null) return "-";
  return (millionWon / 100).toLocaleString("ko-KR", { maximumFractionDigits: 0 }) + "억";
}
function pct(fraction: number | null | undefined): string {
  if (fraction == null) return "-";
  return (fraction * 100).toFixed(1) + "%";
}
function shares(v: number | null | undefined): string {
  if (v == null) return "-";
  return Math.round(v).toLocaleString("ko-KR");
}
function won(v: number | null | undefined): string {
  if (v == null) return "-";
  return Math.round(v).toLocaleString("ko-KR");
}

// **볼드** + 문단(\n\n) 만 허용하는 최소 렌더(flow 해석 규약과 동일 — JS 0줄, escape 안전).
function Interpretation({ text }: { text: string }) {
  const paragraphs = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  return (
    <div className="space-y-3 text-[14px] leading-relaxed text-slate-700">
      {paragraphs.map((para, i) => (
        <p key={i}>
          {para.split(/(\*\*[^*]+\*\*)/).map((seg, j) =>
            seg.startsWith("**") && seg.endsWith("**") ? (
              <b key={j} className="font-bold text-slate-900">
                {seg.slice(2, -2)}
              </b>
            ) : (
              <Fragment key={j}>{seg}</Fragment>
            ),
          )}
        </p>
      ))}
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="mb-4 text-[13px] font-extrabold uppercase tracking-wider text-slate-400">{title}</h2>
      {children}
    </section>
  );
}

function GateBadge({ label, passed }: { label: string; passed: boolean | null | undefined }) {
  const ok = passed === true;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-[11px] font-bold ${
        ok ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-400"
      }`}
    >
      {ok ? <ShieldCheck className="h-3.5 w-3.5" /> : <ShieldAlert className="h-3.5 w-3.5" />}
      {label}
    </span>
  );
}

export function FlowReportView({ payload }: { payload: FlowPayload }) {
  const meta = payload.meta ?? {};
  const s = payload.signals ?? {};
  const v = payload.verification ?? {};
  const dataLimited = payload.data_status === "data_limited";

  return (
    <div className="space-y-5">
      {/* 헤더 */}
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-100 pb-4">
        <div>
          <div className="text-[22px] font-extrabold tracking-tight text-slate-900">
            {meta.stock_name ?? "-"}{" "}
            <span className="text-[15px] font-bold text-slate-400">{meta.ticker ?? ""}</span>
          </div>
          <div className="mt-1 text-[12.5px] font-medium text-slate-500">
            수급·자금흐름 리포트 · 기준일 {meta.base_date ?? "-"}
            {meta.market ? ` · ${meta.market}` : ""}
          </div>
        </div>
        <span
          className={`rounded-lg px-2.5 py-1 text-[11px] font-bold ${
            dataLimited ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"
          }`}
        >
          {dataLimited ? "데이터 제한(data_limited)" : "데이터 정상(ok)"}
        </span>
      </div>

      {/* 해석 */}
      {payload.interpretation ? (
        <Card title="AI 해석 (검증된 사실 기반)">
          <Interpretation text={payload.interpretation} />
          {payload.interpretation_meta?.model ? (
            <div className="mt-3 text-[11px] font-medium text-slate-400">
              해석 모델: {payload.interpretation_meta.provider ?? ""} · {payload.interpretation_meta.model}
            </div>
          ) : null}
        </Card>
      ) : (
        <Card title="AI 해석">
          <p className="text-[13px] text-slate-500">
            검증 게이트(해석↔사실)를 통과한 해석이 없어 사실만 표시합니다(fact_only).
          </p>
        </Card>
      )}

      {/* 투자자별 수급 */}
      <Card title="투자자별 수급 (개인 · 외국인 · 기관)">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {INVESTORS.map((who) => {
            const st = s.strength?.[who];
            const co = s.consecutive?.[who];
            const pe = s.persistence?.[who];
            const net5 = pe?.sum_5 ?? 0;
            const positive = net5 >= 0;
            return (
              <div key={who} className="rounded-xl border border-slate-100 bg-slate-50/60 p-4">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-bold text-slate-800">{who}</span>
                  {st?.strong ? (
                    <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-bold text-indigo-600">
                      강한 수급
                    </span>
                  ) : null}
                </div>
                <div className={`mt-2 text-[18px] font-extrabold ${positive ? "text-rose-600" : "text-blue-600"}`}>
                  {positive ? "＋" : "－"}
                  {eok(Math.abs(net5))}
                  <span className="ml-1 text-[11px] font-bold text-slate-400">5일 순매수</span>
                </div>
                <dl className="mt-2 space-y-1 text-[11.5px] text-slate-500">
                  <div className="flex justify-between">
                    <dt>20일 합</dt>
                    <dd className="font-semibold text-slate-700">{eok(pe?.sum_20)}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>강도(거래대금 대비)</dt>
                    <dd className="font-semibold text-slate-700">{pct(st?.ratio)}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>연속 순매수</dt>
                    <dd className="font-semibold text-slate-700">{co?.days ?? 0}일</dd>
                  </div>
                </dl>
              </div>
            );
          })}
        </div>
        <div className="mt-3 text-[12px] font-medium text-slate-500">
          매매 정렬: <b className="font-bold text-slate-800">{s.alignment ?? "-"}</b>
        </div>
      </Card>

      {/* 날짜별 시세 */}
      {s.price_daily && s.price_daily.length > 0 ? (
        <Card title="날짜별 시세 · 순매매">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-right text-[12px]">
              <thead>
                <tr className="border-b border-slate-200 text-[11px] font-bold text-slate-400">
                  <th className="py-2 text-left">날짜</th>
                  <th className="py-2">종가</th>
                  <th className="py-2">전일비</th>
                  <th className="py-2">등락률</th>
                  <th className="py-2">거래량</th>
                  <th className="py-2">외국인(주)</th>
                  <th className="py-2">기관(주)</th>
                </tr>
              </thead>
              <tbody>
                {s.price_daily.map((r) => {
                  const up = r.change >= 0;
                  return (
                    <tr key={r.date} className="border-b border-slate-50">
                      <td className="py-1.5 text-left font-medium text-slate-600">{r.date}</td>
                      <td className="py-1.5 font-semibold text-slate-800">{won(r.close)}</td>
                      <td className={`py-1.5 ${up ? "text-rose-600" : "text-blue-600"}`}>
                        {up ? "+" : ""}
                        {won(r.change)}
                      </td>
                      <td className={`py-1.5 ${up ? "text-rose-600" : "text-blue-600"}`}>
                        {up ? "+" : ""}
                        {r.change_rate}%
                      </td>
                      <td className="py-1.5 text-slate-500">{shares(r.volume)}</td>
                      <td className={`py-1.5 ${(r.frgn_qty ?? 0) >= 0 ? "text-rose-500" : "text-blue-500"}`}>
                        {shares(r.frgn_qty)}
                      </td>
                      <td className={`py-1.5 ${(r.inst_qty ?? 0) >= 0 ? "text-rose-500" : "text-blue-500"}`}>
                        {shares(r.inst_qty)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {/* 검증 (이 프로젝트의 정체성) */}
      <Card title="검증 게이트">
        <div className="flex flex-wrap items-center gap-2">
          <GateBadge label="게이트1 입력" passed={v.gate1?.passed} />
          <GateBadge label="게이트2 사실↔데이터" passed={v.gate2?.passed} />
          <GateBadge label="게이트3 해석↔사실" passed={v.gate3?.passed} />
          <span className="ml-1 text-[11.5px] font-medium text-slate-500">
            결과: <b className="font-bold text-slate-800">{v.outcome ?? "-"}</b>
            {typeof v.regen_count === "number" ? ` · 재생성 ${v.regen_count}회` : ""}
          </span>
        </div>
        {[v.gate1, v.gate2, v.gate3].some((g) => g && g.checks && g.checks.length > 0) ? (
          <details className="mt-3">
            <summary className="cursor-pointer text-[12px] font-bold text-indigo-600">
              검증 근거(checks) 펼치기
            </summary>
            <div className="mt-2 space-y-2">
              {([["게이트1", v.gate1], ["게이트2", v.gate2], ["게이트3", v.gate3]] as const).map(
                ([label, g]) =>
                  g && g.checks && g.checks.length > 0 ? (
                    <div key={label}>
                      <div className="text-[11px] font-bold text-slate-500">{label}</div>
                      <ul className="ml-4 list-disc text-[11.5px] text-slate-600">
                        {g.checks.map((c, i) => (
                          <li key={i}>{c}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null,
              )}
            </div>
          </details>
        ) : null}
      </Card>
    </div>
  );
}
