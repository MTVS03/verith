import { Fragment } from "react";

import type { FlowPayload, FlowGate, FlowPriceRow } from "@/api/flow";

// flow 리포트를 payload(JSON)에서 그린다 — HTML 저장 안 함(storage-spec §0).
// 디자인·파생 규칙은 flow 에이전트의 render(builder.py + supply_demand.html 목업)를 충실히 포팅:
// 모든 숫자는 signals(검증분) 그대로, 여기서 하는 건 표시용 재표현(부호→단어·스케일→막대폭·포맷)뿐.
// 색 언어: 매수=#F04452(빨강) · 매도=#3182F6(파랑) · 통과=#15A46E(초록) · 중립=#8B95A1.

const SUBJECTS = ["개인", "외국인", "기관"] as const;
const BUY = "#F04452";
const SELL = "#3182F6";
const MUT = "#8B95A1";

// 표시용 임계값(ai flow config 의 사본 — 툴팁 문구 전용, 판정은 payload 가 이미 확정).
const RECENT_DAYS = 5;
const TREND_DAYS = 20;
const CONSEC_THRESHOLD = 3;
const STRENGTH_THRESHOLD_PCT = "12%";

// 기관 세부 표시 규칙(builder._inst_detail_view 와 동일): 5개만, 5일 합 내림차순, 공식명 병기.
const DETAIL_LABELS: Record<string, string> = { 기금: "기금(연기금)", 증권: "증권(금융투자)" };
const DETAIL_DISPLAY = ["기금", "증권", "투자신탁", "사모펀드", "보험"] as const;

function cls(v: number): string {
  return v > 0 ? "buy" : v < 0 ? "sell" : "mut";
}
function color(v: number): string {
  return v > 0 ? BUY : v < 0 ? SELL : MUT;
}
function fmtSigned(v: number): string {
  return `${v > 0 ? "+" : ""}${Math.round(v).toLocaleString("ko-KR")}`;
}
function fmtEok(millionWon: number): string {
  const eok = millionWon / 100;
  return `${eok > 0 ? "+" : ""}${eok.toLocaleString("ko-KR", { maximumFractionDigits: 1, minimumFractionDigits: 1 })}억원`;
}
function shortDate(iso: string): string {
  return (iso || "").slice(5).replace("-", "/");
}

// ── 파생 뷰(builder.py 의 표시용 재표현을 1:1 포팅) ──────────────────────────

type FactRow = {
  name: string;
  days: number | null;
  consecSignal: boolean;
  ratio: number | null;
  strong: boolean;
  direction: "매수" | "매도" | "중립";
  pct: string;
  amt: string | null;
  raw5: number | null;
  barW: number;
};

function factRows(s: NonNullable<FlowPayload["signals"]>): FactRow[] {
  const ratios = SUBJECTS.map((n) => s.strength?.[n]?.ratio ?? null);
  const maxAbs = Math.max(0, ...ratios.filter((r): r is number => r != null).map(Math.abs));
  return SUBJECTS.map((name, i) => {
    const r = ratios[i];
    const direction = r == null || r === 0 ? "중립" : r > 0 ? "매수" : "매도";
    const v5 = s.persistence?.[name]?.sum_5;
    return {
      name,
      days: s.consecutive?.[name]?.days ?? null,
      consecSignal: Boolean(s.consecutive?.[name]?.signal),
      ratio: r,
      strong: Boolean(s.strength?.[name]?.strong),
      direction,
      pct: r == null ? "N/A" : `${r > 0 ? "+" : ""}${(r * 100).toFixed(1)}%`,
      amt: v5 == null ? null : fmtEok(v5),
      raw5: v5 ?? null,
      barW: r == null || !maxAbs ? 0 : Math.round((Math.abs(r) / maxAbs) * 500) / 10,
    };
  });
}

// 수급 종합 게이지 — 외국인+기관 강도 합의 부호(재표현, builder._gauge 와 동일 규칙·아크).
function gaugeView(s: NonNullable<FlowPayload["signals"]>) {
  const fore = s.strength?.["외국인"]?.ratio ?? 0;
  const inst = s.strength?.["기관"]?.ratio ?? 0;
  const sum = fore + inst;
  if (sum > 0)
    return { verdict: "매수 우위", color: BUY, arc: "M 140 30 A 110 110 0 0 1 237.1 88.4", kx: 237.1, ky: 88.4 };
  if (sum < 0)
    return { verdict: "매도 우위", color: SELL, arc: "M 42.9 88.4 A 110 110 0 0 1 140 30", kx: 42.9, ky: 88.4 };
  return { verdict: "중립", color: MUT, arc: null, kx: 140, ky: 30 };
}

function headline(rows: FactRow[]): string {
  const buyers = rows.filter((r) => r.direction === "매수").map((r) => r.name);
  const sellers = rows.filter((r) => r.direction === "매도").map((r) => r.name);
  if (buyers.length && sellers.length) return `${buyers.join("·")}이 사고, ${sellers.join("·")}이 파는 국면`;
  if (buyers.length) return `${buyers.join("·")} 매수 국면`;
  if (sellers.length) return `${sellers.join("·")} 매도 국면`;
  return "방향이 뚜렷하지 않은 국면";
}

// ── 해석 하이라이트 렌더 ─────────────────────────────────────────────────────
// **볼드** → 노란 형광펜(목업 .concl b), 부호 달린 수치(+1,234.5억원 / -5.3% / ▲500원)는
// 매수·매도 색으로 — 둘 다 표시용 강조일 뿐 문장은 그대로다(재작성 없음).
const NUM_RE = /([+\-−▲▼][\d,]+(?:\.\d+)?\s?(?:억원|백만원|만주|원|%p|%|주)?)/g;

function ColoredText({ text }: { text: string }) {
  const parts = text.split(NUM_RE);
  return (
    <>
      {parts.map((seg, i) => {
        if (i % 2 === 1) {
          const negative = seg.startsWith("-") || seg.startsWith("−") || seg.startsWith("▼");
          return (
            <b key={i} className="font-bold" style={{ color: negative ? SELL : BUY }}>
              {seg}
            </b>
          );
        }
        return <Fragment key={i}>{seg}</Fragment>;
      })}
    </>
  );
}

// 문장 선두의 수급 주체를 진하게 — 스캔 가독성(문장 자체는 그대로).
const SUBJECT_LEAD_RE = /^(개인|외국인|기관|증권|투자신탁|사모펀드|기금|보험|종금)/;

function SentenceText({ text }: { text: string }) {
  const m = SUBJECT_LEAD_RE.exec(text);
  if (!m) return <ColoredText text={text} />;
  return (
    <>
      <b className="font-extrabold text-[#191F28]">{m[1]}</b>
      <ColoredText text={text.slice(m[1].length)} />
    </>
  );
}

function Interpretation({ text }: { text: string }) {
  const paragraphs = text.split(/\n+/).map((p) => p.trim()).filter(Boolean);
  return (
    <div className="space-y-4">
      {paragraphs.map((para, i) => {
        // 핵심 문장(**볼드** 포함 문단) → 콜아웃 박스로 크게.
        if (para.includes("**")) {
          return (
            <div key={i} className="rounded-2xl border-l-4 border-[#FFD666] bg-[#FFF9E8] px-5 py-4 text-[16.5px] font-bold leading-[1.7] text-[#191F28]">
              {para.split(/(\*\*[^*]+\*\*)/).map((seg, j) =>
                seg.startsWith("**") && seg.endsWith("**") ? (
                  <ColoredText key={j} text={seg.slice(2, -2)} />
                ) : (
                  <span key={j} className="font-semibold text-[#4E5968]">
                    <ColoredText text={seg} />
                  </span>
                ),
              )}
            </div>
          );
        }
        // 사실 서술 문단 → 문장 단위 리스트(숫자 밀도가 높아 줄 단위 스캔이 훨씬 쉽다).
        const sentences = para.split(/(?<=다\.)\s+/).map((s) => s.trim()).filter(Boolean);
        return (
          <ul key={i} className="space-y-2.5">
            {sentences.map((sen, j) => (
              <li key={j} className="relative pl-4 text-[15px] font-medium leading-[1.75] text-[#333D4B]">
                <span className="absolute left-0 top-[0.66em] h-1.5 w-1.5 rounded-full bg-[#D1D6DB]" />
                <SentenceText text={sen} />
              </li>
            ))}
          </ul>
        );
      })}
    </div>
  );
}

// ── 공용 소품 ────────────────────────────────────────────────────────────────

function Card({ id, title, cap, children }: { id?: string; title?: string; cap?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-4 rounded-[22px] bg-white p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] sm:px-8 sm:py-7">
      {title ? <h2 className="text-[15px] font-extrabold tracking-tight text-[#191F28]">{title}</h2> : null}
      {cap ? <div className="mb-4 mt-1 text-[12.5px] text-[#8B95A1]">{cap}</div> : title ? <div className="mb-4" /> : null}
      {children}
    </section>
  );
}

function Placeholder({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-[14px] border-[1.5px] border-dashed border-[#E5E8EB] px-5 py-8 text-center text-[13.5px] text-[#8B95A1]">
      {children}
    </div>
  );
}

// CSS-only 호버 툴팁(목업 .tip 디자인) — 부모에 `group relative` 필요. JS 없음(서버 컴포넌트 유지).
function HoverTip({ align = "center", children }: { align?: "left" | "center" | "right"; children: React.ReactNode }) {
  const pos =
    align === "left" ? "left-0" : align === "right" ? "right-0" : "left-1/2 -translate-x-1/2";
  return (
    <div
      className={`pointer-events-none absolute bottom-full ${pos} z-20 mb-2 whitespace-nowrap rounded-[9px] bg-[#333D4B] px-3 py-2 text-left text-[11.5px] font-medium leading-relaxed text-white opacity-0 shadow-lg transition-opacity duration-150 group-hover:opacity-100`}
    >
      {children}
    </div>
  );
}

function Chip({ on, label }: { on: boolean; label: string }) {
  return on ? (
    <span className="inline-block rounded-[7px] bg-[#15A46E]/10 px-2 py-0.5 text-[11.5px] font-bold text-[#15A46E]">{label}</span>
  ) : (
    <span className="inline-block rounded-[7px] bg-[#F2F4F6] px-2 py-0.5 text-[11.5px] font-bold text-[#B0B8C1]">–</span>
  );
}

// ── 메인 뷰 ──────────────────────────────────────────────────────────────────

export function FlowReportView({ payload }: { payload: FlowPayload }) {
  const meta = payload.meta ?? { stock_name: null, ticker: null, market: null, base_date: null };
  const s = payload.signals ?? {};
  const v = payload.verification ?? {};
  const dataLimited = payload.data_status === "data_limited";

  const rows = factRows(s);
  const gauge = gaugeView(s);

  // 헤더 종가(builder._header_price): price_daily 마지막 행.
  const priceDaily = s.price_daily ?? null;
  const lastPrice: FlowPriceRow | null = priceDaily?.length ? priceDaily[priceDaily.length - 1] : null;

  // 일별 순매수 차트(builder._daily_view): 최대 |값| 기준 48% 스케일.
  const daily = s.daily ?? null;
  const dailyMax = daily?.length
    ? Math.max(0, ...daily.flatMap((row) => SUBJECTS.map((n) => Math.abs(Number(row[n] ?? 0)))))
    : 0;

  // 지속성(builder._persistence_view): 최대 |합| 기준 100% 스케일 + verdict 문구 조립.
  const persistence = s.persistence ?? null;
  const persistMax = persistence
    ? Math.max(0, ...SUBJECTS.flatMap((n) => [Math.abs(persistence[n]?.sum_5 ?? 0), Math.abs(persistence[n]?.sum_20 ?? 0)]))
    : 0;
  const consBuy = SUBJECTS.filter((n) => persistence?.[n]?.consistent && (persistence[n]?.sum_20 ?? 0) > 0);
  const consSell = SUBJECTS.filter((n) => persistence?.[n]?.consistent && (persistence[n]?.sum_20 ?? 0) < 0);
  const inconsistent = SUBJECTS.filter((n) => persistence && !persistence[n]?.consistent);
  const persistVerdict = [
    consBuy.length ? `${consBuy.join("·")}은 5일·20일 모두 순매수` : null,
    consSell.length ? `${consSell.join("·")}은 5일·20일 모두 순매도` : null,
    inconsistent.length ? `${inconsistent.join("·")}은 5일과 20일 방향이 다름` : null,
  ].filter(Boolean).join(" · ");

  // 기관 세부(builder._inst_detail_view): 표시 5개·내림차순·주도 문구.
  const instDetail = s.inst_detail ?? null;
  const instShown = instDetail
    ? DETAIL_DISPLAY.filter((n) => instDetail[n] != null).map((n) => [n, instDetail[n]] as const).sort((a, b) => b[1] - a[1])
    : [];
  const instMax = instShown.length ? Math.max(...instShown.map(([, val]) => Math.abs(val))) : 0;
  const instLeader = instShown.length
    ? instShown[0][1] > 0 ? `${DETAIL_LABELS[instShown[0][0]] ?? instShown[0][0]} 주도` : "세부 전반 순매도"
    : null;

  // 한도소진율(builder._ownership_view): min-max 스케일(26~90px) + 처음↔끝 delta.
  const ownership = s.ownership ?? null;
  const ownRatios = ownership?.map((r) => r.ratio) ?? [];
  const ownLo = ownRatios.length ? Math.min(...ownRatios) : 0;
  const ownSpan = ownRatios.length ? Math.max(...ownRatios) - ownLo : 0;
  const ownDelta = ownRatios.length ? ownRatios[ownRatios.length - 1] - ownRatios[0] : 0;

  const gates: Array<[string, FlowGate | null | undefined]> = [
    ["입력 확인", v.gate1],
    ["데이터 검증", v.gate2],
    ["해석 검증", v.gate3],
  ];
  const checksTotal = gates.reduce(
    (n, [, g]) => n + (g?.checks?.length ?? 0) + (g?.failures?.length ?? 0),
    0,
  );

  return (
    <div className="break-keep text-[#191F28]" style={{ fontVariantNumeric: "tabular-nums" }}>
      {/* ── 헤더 ── */}
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4 px-1">
        <div>
          <h1 className="text-[26px] font-extrabold tracking-tight">
            {meta.stock_name ?? "-"}
            <span className="ml-1.5 text-[17px] font-semibold text-[#8B95A1]">{meta.ticker ?? ""}</span>
            {meta.market ? (
              <span className="ml-2 inline-block -translate-y-[3px] rounded-lg bg-white px-2.5 py-1 text-xs font-bold text-[#4E5968]">
                {meta.market}
              </span>
            ) : null}
          </h1>
          {lastPrice ? (
            <div className="mt-2.5 flex items-baseline gap-2.5">
              <span className="text-[30px] font-extrabold tracking-tight">{Math.round(lastPrice.close).toLocaleString("ko-KR")}</span>
              <span className="text-[15px] font-bold" style={{ color: color(lastPrice.change) }}>
                {lastPrice.change > 0 ? "▲ " : lastPrice.change < 0 ? "▼ " : "― "}
                {Math.abs(Math.round(lastPrice.change)).toLocaleString("ko-KR")} ({lastPrice.change_rate > 0 ? "+" : ""}
                {lastPrice.change_rate}%)
              </span>
            </div>
          ) : null}
          <div className="mt-1.5 text-sm text-[#4E5968]">기준일 {meta.base_date ?? "-"} 종가</div>
        </div>
        <div className="pt-1 text-right">
          <div className="text-[13px] font-semibold text-[#8B95A1]">수급 검증 리포트</div>
          <span
            className="mt-2 inline-block rounded-lg px-2.5 py-1 text-[11px] font-bold"
            style={dataLimited ? { background: "#FFF3D6", color: "#9a6c10" } : { background: "rgba(21,164,110,0.1)", color: "#15A46E" }}
          >
            {dataLimited ? "데이터 일부 제한" : "데이터 정상"}
          </span>
        </div>
      </header>

      {/* ── 2단 그리드: 본문 + 사이드바 ── */}
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_296px]">
        <main className="flex min-w-0 flex-col gap-5">
          {/* [A] 요약: 게이지 + 헤드라인 + 3주체 강도 바 */}
          <Card id="summary">
            <div className="grid items-center gap-8 md:grid-cols-[280px_minmax(0,1fr)]">
              <div>
                <div className="mb-1.5 text-center text-[13px] font-bold text-[#8B95A1]">수급 종합 게이지</div>
                <svg viewBox="0 0 280 172" className="mx-auto block w-[260px]">
                  <path d="M 30 140 A 110 110 0 0 1 250 140" fill="none" stroke="#E5E8EB" strokeWidth="20" strokeLinecap="round" />
                  {gauge.arc ? <path d={gauge.arc} fill="none" stroke={gauge.color} strokeWidth="20" strokeLinecap="round" /> : null}
                  <circle cx={gauge.kx} cy={gauge.ky} r="13" fill="#fff" stroke={gauge.color} strokeWidth="5" />
                  <text x="42" y="163" fontSize="12.5" fill={SELL} fontWeight="700" textAnchor="middle">매도 우위</text>
                  <text x="140" y="20" fontSize="12" fill="#B0B8C1" fontWeight="600" textAnchor="middle">중립</text>
                  <text x="238" y="163" fontSize="12.5" fill={BUY} fontWeight="700" textAnchor="middle">매수 우위</text>
                </svg>
                <div
                  className="mt-1.5 cursor-help text-center text-[30px] font-extrabold leading-none tracking-tight"
                  style={{ color: gauge.color }}
                  title={`최근 ${RECENT_DAYS}거래일 순매수 강도 기준 — 외국인·기관 강도 합의 부호로 판정합니다`}
                >
                  {gauge.verdict}
                </div>
              </div>
              <div>
                <div className="mb-5 text-[23px] font-extrabold leading-[1.35] tracking-tight">{headline(rows)}</div>
                {rows.map((r) => (
                  <div key={r.name} className="group relative mb-3 flex items-center gap-3.5">
                    <HoverTip>
                      <div className="font-bold">{r.name} · 최근 {RECENT_DAYS}거래일</div>
                      <div>순매수 합 {r.raw5 == null ? "N/A" : `${fmtSigned(r.raw5)}백만원 (${r.amt})`}</div>
                      <div>하루평균 거래대금 대비 {r.pct} · +매수 −매도</div>
                    </HoverTip>
                    <span className="w-[52px] flex-shrink-0 text-right text-sm font-bold text-[#4E5968]">{r.name}</span>
                    <div className="relative h-[34px] flex-1 overflow-hidden rounded-[9px] bg-[#F2F4F6]">
                      <div className="absolute bottom-0 left-1/2 top-0 w-[2px] bg-[#D1D6DB]" />
                      {r.direction === "매수" ? (
                        <div className="absolute bottom-[5px] left-1/2 top-[5px] rounded-md" style={{ width: `${r.barW}%`, background: BUY }} />
                      ) : r.direction === "매도" ? (
                        <div className="absolute bottom-[5px] right-1/2 top-[5px] rounded-md" style={{ width: `${r.barW}%`, background: SELL }} />
                      ) : null}
                    </div>
                    <span
                      className="w-[96px] flex-shrink-0 cursor-help text-right text-sm font-extrabold"
                      style={{ color: r.direction === "매수" ? BUY : r.direction === "매도" ? SELL : MUT }}
                    >
                      {r.amt ?? r.pct}
                      {r.amt ? <span className="block text-[11px] font-semibold text-[#8B95A1]">거래대금의 {r.pct}</span> : null}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          {/* 날짜별 시세 — 최신이 위(시세표 관행) */}
          <Card id="price" title="날짜별 시세" cap={`최근 ${priceDaily?.length ?? 0}거래일 · 종가·전일비 원 · 거래량·순매매량 주 · 최신이 위`}>
            {priceDaily?.length ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[600px] border-collapse text-[13px]">
                  <thead>
                    <tr>
                      {["날짜", "종가", "전일비", "등락률", "거래량", "기관 순매매량", "외국인 순매매량"].map((h, i) => (
                        <th key={h} className={`whitespace-nowrap border-b border-[#E5E8EB] px-2.5 py-2 text-xs font-bold text-[#8B95A1] ${i === 0 ? "text-left" : "text-right"}`}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...priceDaily].reverse().map((r) => (
                      <tr key={r.date}>
                        <td className="whitespace-nowrap border-b border-[#F2F4F6] px-2.5 py-2 text-left font-bold text-[#4E5968]">{shortDate(r.date)}</td>
                        <td className="border-b border-[#F2F4F6] px-2.5 py-2 text-right text-[#333D4B]">{Math.round(r.close).toLocaleString("ko-KR")}</td>
                        <td className="whitespace-nowrap border-b border-[#F2F4F6] px-2.5 py-2 text-right" style={{ color: color(r.change) }}>
                          {r.change > 0 ? "▲ " : r.change < 0 ? "▼ " : "― "}
                          {Math.abs(Math.round(r.change)).toLocaleString("ko-KR")}
                        </td>
                        <td className="border-b border-[#F2F4F6] px-2.5 py-2 text-right" style={{ color: color(r.change) }}>
                          {r.change_rate > 0 ? "+" : ""}
                          {r.change_rate}%
                        </td>
                        <td className="border-b border-[#F2F4F6] px-2.5 py-2 text-right text-[#333D4B]">{Math.round(r.volume).toLocaleString("ko-KR")}</td>
                        <td className="border-b border-[#F2F4F6] px-2.5 py-2 text-right" style={{ color: r.inst_qty == null ? MUT : color(r.inst_qty) }}>
                          {r.inst_qty == null ? "—" : fmtSigned(r.inst_qty)}
                        </td>
                        <td className="border-b border-[#F2F4F6] px-2.5 py-2 text-right" style={{ color: r.frgn_qty == null ? MUT : color(r.frgn_qty) }}>
                          {r.frgn_qty == null ? "—" : fmtSigned(r.frgn_qty)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Placeholder>데이터 준비 중 — 날짜별 시세가 아직 없습니다.</Placeholder>
            )}
          </Card>

          {/* 투자자별 일별 순매수 차트 */}
          <Card id="daily" title="투자자별 일별 순매수" cap={`최근 ${TREND_DAYS}거래일 · 막대 순서 개인·외국인·기관(음영은 개인) · 단위 백만원 · +매수 −매도`}>
            {daily?.length ? (
              <>
                <div className="relative mt-1 flex h-[230px] gap-1.5">
                  <div className="absolute left-0 right-0 top-1/2 h-[2px] bg-[#D1D6DB]" />
                  {daily.map((row, di) => {
                    const iso = String(row.date ?? "");
                    // 가장자리 열은 툴팁이 카드 밖으로 넘치지 않게 정렬을 바꾼다.
                    const align = di < 3 ? "left" : di >= daily.length - 3 ? "right" : "center";
                    return (
                      <div key={iso} className="group relative flex min-w-0 flex-1 flex-col rounded-md transition-colors hover:bg-[#F7F8FA]">
                        <HoverTip align={align}>
                          <div className="mb-0.5 font-bold">{iso}</div>
                          {SUBJECTS.map((name) => {
                            const val = Number(row[name] ?? 0);
                            return (
                              <div key={name} className="flex items-center gap-1.5">
                                <span className="inline-block h-2 w-2 rounded-[2px]" style={{ background: val > 0 ? BUY : val < 0 ? SELL : MUT }} />
                                {name} {fmtSigned(val)}백만원
                              </div>
                            );
                          })}
                        </HoverTip>
                        <div className="flex flex-1 justify-center gap-[2px]">
                          {SUBJECTS.map((name, i) => {
                            const val = Number(row[name] ?? 0);
                            const h = dailyMax && val ? Math.round((Math.abs(val) / dailyMax) * 480) / 10 : 0;
                            return (
                              <div key={name} className={`relative w-[9px] ${i === 0 ? "rounded-[3px] bg-[#F7F8FA]" : ""}`}>
                                {h > 0 ? (
                                  val > 0 ? (
                                    <div className="absolute inset-x-0 bottom-1/2 rounded-t-[3px]" style={{ height: `${h}%`, background: BUY }} />
                                  ) : (
                                    <div className="absolute inset-x-0 top-1/2 rounded-b-[3px]" style={{ height: `${h}%`, background: SELL }} />
                                  )
                                ) : null}
                              </div>
                            );
                          })}
                        </div>
                        <div className="mt-1.5 overflow-hidden whitespace-nowrap text-center text-[9.5px] text-[#B0B8C1]">{shortDate(iso)}</div>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-3 flex gap-3.5 text-xs text-[#8B95A1]">
                  <span><span className="mr-1.5 inline-block h-[9px] w-[9px] rounded-[3px] align-[-1px]" style={{ background: BUY }} />순매수</span>
                  <span><span className="mr-1.5 inline-block h-[9px] w-[9px] rounded-[3px] align-[-1px]" style={{ background: SELL }} />순매도</span>
                  <span><span className="mr-1.5 inline-block h-[9px] w-[9px] rounded-[3px] border border-[#E5E8EB] bg-[#F7F8FA] align-[-1px]" />개인 트랙 음영</span>
                </div>
              </>
            ) : (
              <Placeholder>데이터 준비 중 — 일별 순매수 시계열이 아직 없습니다.</Placeholder>
            )}
          </Card>

          {/* 지속성 5일 vs 20일 */}
          <Card id="persist" title="지속성 · 5일 vs 20일" cap="최근 흐름이 일시적인지, 20일에 걸쳐 지속되는지 · 단위 백만원">
            {persistence ? (
              <>
                {SUBJECTS.map((name) => {
                  const p = persistence[name] ?? { sum_5: 0, sum_20: 0, consistent: false };
                  return (
                    <div key={name} className="group relative flex items-center gap-3.5 border-b border-[#F2F4F6] py-2.5 last:border-b-0">
                      <HoverTip>
                        <div className="font-bold">{name}</div>
                        <div>5일 합 {fmtSigned(p.sum_5 ?? 0)}백만원 ({fmtEok(p.sum_5 ?? 0)})</div>
                        <div>20일 합 {fmtSigned(p.sum_20 ?? 0)}백만원 ({fmtEok(p.sum_20 ?? 0)})</div>
                        <div>방향 {p.consistent ? "일관(5일·20일 같은 방향)" : "상이(5일과 20일 방향 다름)"}</div>
                      </HoverTip>
                      <span className="w-[52px] flex-shrink-0 text-right text-sm font-bold text-[#4E5968]">{name}</span>
                      <div className="flex min-w-0 flex-1 flex-col gap-[5px]">
                        {([["5일", p.sum_5, false], ["20일", p.sum_20, true]] as const).map(([label, val, dim]) => (
                          <div key={label} className="flex items-center gap-2">
                            <span className="w-[34px] text-right text-[11px] font-bold text-[#B0B8C1]">{label}</span>
                            <div className="h-3.5 flex-1 overflow-hidden rounded-[5px] bg-[#F2F4F6]">
                              <div
                                className="h-full rounded-[5px]"
                                style={{
                                  width: `${persistMax ? Math.round((Math.abs(val) / persistMax) * 1000) / 10 : 0}%`,
                                  background: color(val),
                                  opacity: dim ? 0.55 : 1,
                                }}
                              />
                            </div>
                            <span className="w-[92px] flex-shrink-0 text-right text-[12.5px] font-extrabold" style={{ color: color(val) }}>
                              {fmtSigned(val)}
                            </span>
                          </div>
                        ))}
                      </div>
                      <Chip on={Boolean(p.consistent)} label="일관" />
                    </div>
                  );
                })}
                {persistVerdict ? <div className="mt-3 text-[13px] leading-relaxed text-[#4E5968]">{persistVerdict}</div> : null}
              </>
            ) : (
              <Placeholder>데이터 준비 중 — 지속성 비교가 아직 없습니다.</Placeholder>
            )}
          </Card>

          {/* 판정 근거 3카드 */}
          <Card id="signals" title="판정 근거">
            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-2xl bg-[#F9FAFB] p-4.5 px-5 py-4">
                <div className="mb-2.5 cursor-help text-[12.5px] font-bold text-[#8B95A1]" title={`${CONSEC_THRESHOLD}일 이상 이어지면 '신호'로 표시합니다`}>
                  연속 순매수 일수
                </div>
                {rows.map((r) => (
                  <div key={r.name} className="flex items-center justify-between py-[3px] text-[13.5px]">
                    <span className="text-[#4E5968]">{r.name}</span>
                    <span className="flex items-center gap-1.5">
                      <b className="font-extrabold">{r.days ?? 0}일</b>
                      <Chip on={r.consecSignal} label="신호" />
                    </span>
                  </div>
                ))}
              </div>
              <div className="rounded-2xl bg-[#F9FAFB] px-5 py-4">
                <div className="mb-2.5 cursor-help text-[12.5px] font-bold text-[#8B95A1]" title={`최근 ${RECENT_DAYS}거래일 순매수 합 ÷ 하루평균 거래대금 · ${STRENGTH_THRESHOLD_PCT} 이상이면 '강함'으로 표시합니다`}>
                  순매수 강도
                </div>
                {rows.map((r) => (
                  <div key={r.name} className="flex items-center justify-between py-[3px] text-[13.5px]">
                    <span className="text-[#4E5968]">{r.name}</span>
                    <span className="flex items-center gap-1.5">
                      <b className="font-extrabold" style={{ color: r.direction === "매수" ? BUY : r.direction === "매도" ? SELL : MUT }}>{r.pct}</b>
                      <Chip on={r.strong} label="강함" />
                    </span>
                  </div>
                ))}
              </div>
              <div className="rounded-2xl bg-[#F9FAFB] px-5 py-4">
                <div className="mb-1 cursor-help text-[12.5px] font-bold text-[#8B95A1]" title={`외국인·기관의 최근 ${RECENT_DAYS}거래일 순매수 방향이 같은지 다른지를 봅니다`}>
                  수급 구도 (외국인·기관)
                </div>
                <div
                  className="my-1.5 text-[22px] font-extrabold tracking-tight"
                  style={{ color: s.alignment === "동반매수" ? BUY : s.alignment === "동반매도" ? SELL : MUT }}
                >
                  {s.alignment ?? "-"}
                </div>
              </div>
            </div>
          </Card>

          {/* 심화: 기관 세부 + 한도소진율 */}
          <Card id="deep" title="심화 · 기관 세부와 외국인 한도소진율">
            <div className="grid gap-5 md:grid-cols-2">
              <div>
                <div className="mb-2.5 text-[12.5px] font-bold text-[#8B95A1]">
                  <span className="cursor-help" title={`최근 ${RECENT_DAYS}거래일 누적 순매수 · 단위 백만원`}>기관 세부 순매수</span>
                  {instLeader ? ` · ${instLeader}` : ""}
                </div>
                {instShown.length ? (
                  instShown.map(([name, val]) => (
                    <div key={name} className="group relative flex items-center gap-2.5 py-[5px]">
                      <HoverTip align="left">
                        <div className="font-bold">{DETAIL_LABELS[name] ?? name}</div>
                        <div>최근 {RECENT_DAYS}거래일 누적 {fmtSigned(val)}백만원 ({fmtEok(val)})</div>
                      </HoverTip>
                      <span className="w-[96px] flex-shrink-0 text-[12.5px] font-bold text-[#4E5968]">{DETAIL_LABELS[name] ?? name}</span>
                      <div className="h-3.5 flex-1 overflow-hidden rounded-[5px] bg-[#F2F4F6]">
                        <div
                          className="h-full rounded-[5px]"
                          style={{ width: `${instMax ? Math.round((Math.abs(val) / instMax) * 1000) / 10 : 0}%`, background: color(val) }}
                        />
                      </div>
                      <span className="w-[84px] flex-shrink-0 text-right text-[12.5px] font-extrabold" style={{ color: color(val) }}>
                        {fmtSigned(val)}
                      </span>
                    </div>
                  ))
                ) : (
                  <Placeholder>데이터 준비 중 — 기관 세부가 아직 없습니다.</Placeholder>
                )}
              </div>
              <div>
                <div className="mb-2.5 cursor-help text-[12.5px] font-bold text-[#8B95A1]" title="외국인이 살 수 있는 한도 대비 실제 보유 비율(%) · 한도가 100%인 대부분 종목은 보유율과 같습니다">
                  외국인 한도소진율 추이
                </div>
                {ownership?.length ? (
                  <>
                    <div className="flex items-baseline gap-2.5">
                      <span className="text-[30px] font-extrabold leading-none tracking-tight">{ownRatios[ownRatios.length - 1].toFixed(2)}%</span>
                      <span className="text-[13px] font-bold" style={{ color: color(ownDelta) }}>
                        {ownDelta > 0 ? "▲" : ownDelta < 0 ? "▼" : "―"} {ownDelta > 0 ? "+" : ""}
                        {ownDelta.toFixed(2)}%p
                      </span>
                    </div>
                    <div className="mt-3.5 flex h-[110px] items-end gap-4 border-b-[1.5px] border-[#E5E8EB] px-1">
                      {ownership.map((r, oi) => {
                        const h = ownSpan ? 26 + ((r.ratio - ownLo) / ownSpan) * 64 : 55;
                        const prev = oi > 0 ? ownership[oi - 1].ratio : null;
                        const dayDelta = prev == null ? null : r.ratio - prev;
                        return (
                          <div key={r.date} className="group relative flex h-full flex-1 flex-col items-center justify-end gap-[7px] rounded-md transition-colors hover:bg-[#F7F8FA]">
                            <HoverTip align={oi === 0 ? "left" : oi === ownership.length - 1 ? "right" : "center"}>
                              <div className="font-bold">{r.date}</div>
                              <div>한도소진율 {r.ratio.toFixed(2)}%</div>
                              {dayDelta != null ? (
                                <div>전일 대비 {dayDelta > 0 ? "+" : ""}{dayDelta.toFixed(2)}%p</div>
                              ) : null}
                            </HoverTip>
                            <span className="text-[11px] text-[#B0B8C1]">{r.ratio.toFixed(2)}</span>
                            <div className="w-full max-w-[30px] rounded-t-[5px] bg-[#FBCBD0]" style={{ height: `${Math.round(h)}px` }} />
                          </div>
                        );
                      })}
                    </div>
                    <div className="flex gap-4 px-1 pt-1.5">
                      {ownership.map((r) => (
                        <span key={r.date} className="flex-1 text-center text-[11px] text-[#B0B8C1]">{shortDate(r.date)}</span>
                      ))}
                    </div>
                  </>
                ) : (
                  <Placeholder>데이터 준비 중 — 외국인 한도소진율이 아직 없습니다.</Placeholder>
                )}
              </div>
            </div>
          </Card>

          {/* 검증 */}
          <Card id="verify" title="검증" cap="이 리포트의 모든 숫자는 표시 전에 코드로 원본과 대조됩니다">
            <div className="flex flex-wrap gap-2">
              {gates.map(([label, g]) =>
                g == null ? null : g.passed ? (
                  <span key={label} className="inline-flex items-center gap-1.5 rounded-full bg-[#15A46E]/10 px-3.5 py-[7px] text-[13.5px] font-bold text-[#15A46E]">✓ {label} 통과</span>
                ) : (
                  <span key={label} className="inline-flex items-center gap-1.5 rounded-full bg-[#F04452]/10 px-3.5 py-[7px] text-[13.5px] font-bold text-[#F04452]">✗ {label} 실패</span>
                ),
              )}
              {typeof v.regen_count === "number" && v.regen_count > 0 ? (
                <span className="inline-flex items-center rounded-full bg-[#F2F4F6] px-3.5 py-[7px] text-[13px] font-bold text-[#4E5968]">해석 재생성 {v.regen_count}회</span>
              ) : null}
            </div>
            {checksTotal > 0 ? (
              <details className="mt-3">
                <summary className="cursor-pointer select-none text-[12.5px] font-semibold text-[#8B95A1] hover:text-[#4E5968]">
                  검증 상세 {checksTotal}건 보기
                </summary>
                <ul className="mt-2.5">
                  {gates.flatMap(([label, g]) => [
                    ...(g?.checks ?? []).map((c, i) => (
                      <li key={`${label}-c${i}`} className="py-[5px] text-[13px] text-[#4E5968]">
                        <span className="font-extrabold text-[#15A46E]">✓ </span>{c}
                      </li>
                    )),
                    ...(g?.failures ?? []).map((f, i) => (
                      <li key={`${label}-f${i}`} className="py-[5px] text-[13px] text-[#4E5968]">
                        <span className="font-extrabold text-[#F04452]">⚠ </span>{f}
                      </li>
                    )),
                  ])}
                </ul>
              </details>
            ) : null}
            <div className="mt-3 text-xs text-[#8B95A1]">출처: 한국투자증권(KIS) Open API · 기준일 {meta.base_date ?? "-"}</div>
          </Card>

          {/* 종합 결론 = AI 해석 (게이트3 통과분만) */}
          <Card id="conclusion" title="종합 결론 · AI 해석">
            {payload.interpretation ? (
              <>
                <div className="mb-4 cursor-help text-[12.5px] text-[#8B95A1]" title="이 해석 문장은 위 팩트와 모순되지 않는지 코드로 대조(검증)를 마친 것입니다">
                  <span className="border-b border-dotted border-[#B0B8C1]">✓ 팩트 대조를 마친 해석</span>
                </div>
                <Interpretation text={payload.interpretation} />
                {payload.interpretation_meta?.model ? (
                  <div className="mt-4 text-[11px] font-medium text-[#B0B8C1]">
                    해석 모델: {payload.interpretation_meta.provider ?? ""} · {payload.interpretation_meta.model} · 숫자·판정은 결정론 코드가 계산, LLM은 검증된 사실의 해석만 담당
                  </div>
                ) : null}
              </>
            ) : (
              <Placeholder>해석 생략 — 검증을 통과한 해석이 없어 팩트만 표시합니다(fact_only).</Placeholder>
            )}
          </Card>

          <div className="px-1.5 text-xs leading-relaxed text-[#8B95A1]">
            ※ 수급 신호이며 주가 예측이 아닙니다. 본 분석은 수급만 다룹니다.
            <br />본 리포트는 투자 자문이 아니며 과거 수급 데이터 기반 참고 자료입니다.
          </div>
        </main>

        {/* ── 사이드바: 목차 + 분석 과정 + 리포트 정보 ── */}
        <aside className="flex flex-col gap-4 lg:sticky lg:top-5 print:hidden">
          <div className="rounded-[20px] bg-white p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <h2 className="mb-2.5 text-[15px] font-extrabold">목차</h2>
            <ul>
              {([
                ["#summary", "요약"],
                ["#price", "날짜별 시세"],
                ["#daily", "투자자별 순매수"],
                ["#persist", "지속성"],
                ["#signals", "판정 근거"],
                ["#deep", "심화"],
                ["#verify", "검증"],
                ["#conclusion", "종합 결론"],
              ] as const).map(([href, label]) => (
                <li key={href} className="py-1.5">
                  <a href={href} className="text-[13.5px] font-semibold text-[#4E5968] hover:text-[#191F28]">{label}</a>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-[20px] bg-white p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <h2 className="mb-2.5 text-[15px] font-extrabold">분석 과정</h2>
            <ul>
              {([
                ["데이터 수집", "KIS Open API · 일별 투자자매매동향"],
                ["신호 계산", "연속·강도·구도 (결정론적 코드)"],
                ["검증 게이트", "팩트↔데이터 · 해석↔팩트 대조"],
                ["리포트 생성", "검증 통과분만 표시"],
              ] as const).map(([t, d], i) => (
                <li key={t} className="flex items-start gap-3 py-2">
                  <span className="flex h-[22px] w-[22px] flex-shrink-0 items-center justify-center rounded-full bg-[#F2F4F6] text-xs font-extrabold text-[#4E5968]">{i + 1}</span>
                  <span>
                    <span className="block text-[13.5px] font-bold">{t}</span>
                    <span className="block text-xs text-[#8B95A1]">{d}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-[20px] bg-white p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <h2 className="mb-2.5 text-[15px] font-extrabold">리포트 정보</h2>
            <dl className="space-y-2 text-xs">
              <div>
                <dt className="font-bold text-[#8B95A1]">리포트 ID</dt>
                <dd className="break-all font-medium text-[#4E5968]">{payload.report_id}</dd>
              </div>
              {payload.trace_id && payload.trace_id !== payload.report_id ? (
                <div>
                  <dt className="font-bold text-[#8B95A1]">추적 ID</dt>
                  <dd className="break-all font-medium text-[#4E5968]">{payload.trace_id}</dd>
                </div>
              ) : null}
              <div>
                <dt className="font-bold text-[#8B95A1]">해석 상태</dt>
                <dd className="font-medium text-[#4E5968]">{v.outcome === "explained" ? "해석 포함(게이트3 통과)" : "팩트만(fact_only)"}</dd>
              </div>
            </dl>
          </div>
        </aside>
      </div>
    </div>
  );
}
