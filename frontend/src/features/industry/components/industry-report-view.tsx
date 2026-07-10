"use client";

import { Fragment, useMemo, useState } from "react";

import type { IndustryPayload } from "@/api/industry";

// industry 리포트를 payload(research-report.v1 JSON)에서 그린다 — iframe(AI HTML) 제거.
// 디자인·로직은 AI 템플릿(ai/src/agents/industry/make_report/report_template.html 의 dc-script,
// = flow/mockup/industry_mokup 목업의 최신본)을 1:1 포팅. 여기서 하는 건 표시용 재표현뿐이고
// 그래프·근거·지표는 payload 가 이미 확정한 값을 그대로 쓴다(재계산 없음).

// ── 관계·노드 색 언어 (템플릿 relColor/relLabel/relSoft/relInk 그대로) ──────
const REL_COLOR: Record<string, string> = {
  SUPPLIES: "#3f6ede", COMPETES_WITH: "#f0435f", BENEFITS_FROM: "#1fb877", BELONGS_TO: "#7c5cff",
  SUPPLY_HUB: "#0f9f8f", COMPETITION_HUB: "#f0435f", COMMUNITY: "#c9cdd6", VECTOR: "#7a828f",
};
const REL_LABEL: Record<string, string> = {
  SUPPLIES: "공급", COMPETES_WITH: "경쟁", BENEFITS_FROM: "정책 수혜", BELONGS_TO: "소속",
  SUPPLY_HUB: "공급 허브", COMPETITION_HUB: "경쟁 중심", COMMUNITY: "커뮤니티", VECTOR: "벡터 근거",
};
const REL_SOFT: Record<string, string> = {
  SUPPLIES: "#eef3ff", BENEFITS_FROM: "#e8f7f0", COMPETES_WITH: "#fde7eb", BELONGS_TO: "#f0edff",
  SUPPLY_HUB: "#e8f7f5", COMPETITION_HUB: "#fde7eb", COMMUNITY: "#f1f3f7", VECTOR: "#f1f3f7",
};
const REL_INK: Record<string, string> = {
  SUPPLIES: "#2b53c0", BENEFITS_FROM: "#157a4f", COMPETES_WITH: "#c22b45", BELONGS_TO: "#5942bd",
  SUPPLY_HUB: "#08776b", COMPETITION_HUB: "#c22b45", COMMUNITY: "#7a828f", VECTOR: "#5a6270",
};
const relColor = (r: string) => REL_COLOR[r] ?? "#c9cdd6";
const relLabel = (r: string) => REL_LABEL[r] ?? r;
const relSoft = (r: string) => REL_SOFT[r] ?? "#f1f3f7";
const relInk = (r: string) => REL_INK[r] ?? "#7a828f";

const NODE_RING: Record<string, string> = {
  upstream: "#1fb877", midstream: "#3f6ede", customer: "#e3a52a", downstream: "#f0435f",
};
const NODE_SOFT: Record<string, string> = {
  upstream: "#e8f7f0", midstream: "#eef3ff", customer: "#fbf2dd", downstream: "#fde7eb",
};

const FAITH_TONE: Record<string, { short: string; main: string; bg: string; fg: string; dot: string }> = {
  verified: { short: "완료", main: "#157a4f", bg: "#e8f7f0", fg: "#157a4f", dot: "#1fb877" },
  warning: { short: "경고", main: "#c58a12", bg: "#faf1dd", fg: "#9a6c10", dot: "#e3a52a" },
  failed: { short: "실패", main: "#c22b45", bg: "#fde7eb", fg: "#c22b45", dot: "#f0435f" },
  unchecked: { short: "미확인", main: "#7a828f", bg: "#f1f3f7", fg: "#7a828f", dot: "#9aa1b0" },
};

// ── payload → 뷰 모델 (템플릿 payloadToView 포팅) ───────────────────────────

type ViewNode = { id: string; label: string; kind: string; x: number; y: number };
type ViewEdge = {
  id: string; source: string; target: string; relation: string; label: string;
  evidence: string[]; dashed: boolean;
};
type ViewEvidence = {
  id: string; relation: string; title: string; quote: string; source: string;
  url: string; hasUrl: boolean;
};
type ViewModel = {
  nodes: ViewNode[];
  edges: ViewEdge[];
  evidence: ViewEvidence[];
  relations: string[];
  svgHeight: number;
  report: {
    schemaLine: string; questionText: string; generatedMeta: string; questionType: string;
    rowCount: number; attemptCount: number;
    answerHeadline: string; answerBody: string; answerTags: string[];
    faithStatus: string; faithLabel: string;
  };
};

const shortId = (id: unknown) => String(id ?? "").replace(/^ev:/, "").replace(/^edge:/, "");

function sourceText(source: NonNullable<IndustryPayload["evidence"]>[number]["source"]): string {
  if (!source) return "";
  return [source.name, source.reportName, source.section, source.bsnsYear].filter(Boolean).join(" · ");
}

// 노드 좌표는 payload(홉 기반 레이아웃)를 그대로 쓰되, 같은 x열에 노드가 몰려 박스(높이 66)가
// 겹치면 그 열의 y 만 등간격으로 재분배한다 — 순서는 payload 의 y 순서 유지(표시용 재배치).
const NODE_H = 66;
const COL_GAP = 78; // 열 안 최소 세로 간격(박스 66 + 여백)
function layoutNodes(nodes: ViewNode[]): { nodes: ViewNode[]; svgHeight: number } {
  const cols = new Map<number, ViewNode[]>();
  for (const n of nodes) {
    const list = cols.get(n.x) ?? [];
    list.push(n);
    cols.set(n.x, list);
  }
  const maxCol = Math.max(1, ...[...cols.values()].map((c) => c.length));
  const svgHeight = Math.max(560, maxCol * COL_GAP + 100);
  for (const list of cols.values()) {
    list.sort((a, b) => a.y - b.y);
    const overlapped = list.some((n, i) => i > 0 && n.y - list[i - 1].y < NODE_H + 6);
    if (!overlapped) continue;
    const span = (list.length - 1) * COL_GAP;
    const start = Math.max(NODE_H / 2 + 10, (svgHeight - span) / 2);
    list.forEach((n, i) => { n.y = start + i * COL_GAP; });
  }
  return { nodes, svgHeight };
}

function payloadToView(payload: IndustryPayload): ViewModel {
  const graph = payload.graph ?? {};
  const rawNodes: ViewNode[] = (graph.nodes ?? []).map((n, i) => ({
    id: String(n.id ?? `node-${i}`),
    label: String(n.label ?? n.id ?? `Node ${i + 1}`),
    kind: String(n.kind ?? "aggregate"),
    x: Number(n.position?.x ?? 120 + (i % 4) * 240),
    y: Number(n.position?.y ?? 120 + Math.floor(i / 4) * 120),
  }));
  const { nodes, svgHeight } = layoutNodes(rawNodes);

  const evidenceByEdge = new Map<string, string[]>();
  for (const ev of payload.evidence ?? []) {
    if (!ev.edgeId) continue;
    const list = evidenceByEdge.get(ev.edgeId) ?? [];
    list.push(shortId(ev.ref ?? ev.id));
    evidenceByEdge.set(ev.edgeId, list);
  }

  const edges: ViewEdge[] = (graph.edges ?? [])
    .map((e, i) => {
      const relation = String(e.relation ?? "COMMUNITY");
      const id = String(e.id ?? `edge-${i}`);
      return {
        id,
        source: String(e.source ?? ""),
        target: String(e.target ?? ""),
        relation,
        label: String(e.label ?? relLabel(relation)),
        evidence: (e.evidenceIds ?? [])
          .map(shortId)
          .concat(evidenceByEdge.get(id) ?? [])
          .filter((v, idx, arr) => Boolean(v) && arr.indexOf(v) === idx),
        dashed: e.style === "dashed" || !["SUPPLIES", "BELONGS_TO"].includes(relation),
      };
    })
    .filter((e) => e.source && e.target);

  const edgeRel = new Map(edges.map((e) => [e.id, e.relation]));
  const evidence: ViewEvidence[] = (payload.evidence ?? []).map((ev) => {
    const source = ev.source ?? {};
    const url = String(source.textFragmentUrl ?? source.url ?? "");
    return {
      id: shortId(ev.ref ?? ev.id),
      relation: String(ev.relation ?? (ev.edgeId ? edgeRel.get(ev.edgeId) : "") ?? "VECTOR") || "VECTOR",
      title: String(ev.title ?? ev.id ?? "근거"),
      quote: String(ev.quote ?? ""),
      source: sourceText(source) || "Neo4j 집계 결과",
      url,
      hasUrl: Boolean(url),
    };
  });

  const metrics = payload.metrics ?? {};
  const answer = payload.answer ?? {};
  const faith = answer.faithfulness ?? {};
  const question = payload.question ?? {};
  const created = String(payload.createdAt ?? "").slice(0, 10).replaceAll("-", ".");

  return {
    nodes,
    edges,
    evidence,
    svgHeight,
    relations: [...new Set(edges.map((e) => e.relation).concat(evidence.map((e) => e.relation)))].filter(Boolean),
    report: {
      schemaLine: `${payload.schemaVersion ?? "research-report.v1"} · ${question.label ?? question.type ?? "graph question"}`,
      questionText: String(question.text ?? ""),
      generatedMeta: created ? `${created} 생성` : "생성일 없음",
      questionType: String(question.type ?? "unknown"),
      rowCount: Number(metrics.rows ?? 0),
      attemptCount: Number(metrics.attempts ?? 0),
      answerHeadline: String(answer.headline ?? "분석 결과"),
      answerBody: String(answer.body ?? ""),
      answerTags: Array.isArray(answer.tags) ? answer.tags : [],
      faithStatus: String(faith.status ?? "unchecked"),
      faithLabel: String(faith.label ?? "근거 검증 정보 없음"),
    },
  };
}

// ── 답변 본문 마크다운-lite (템플릿 parseAnswerBlocks/parseInlineSegs 포팅) ──
// LLM이 내는 그대로의 텍스트를 재작성하지 않고 표기만 바꾼다 — 내용 불변.

type Seg = { bold: string; plain: string };
type Block = { heading: boolean; bullet: boolean; segs: Seg[] };

function parseInlineSegs(text: string): Seg[] {
  return String(text)
    .split(/(\*\*[^*]+\*\*)/)
    .filter((s) => s !== "")
    .map((s) => {
      const m = /^\*\*([^*]+)\*\*$/.exec(s);
      return m ? { bold: m[1], plain: "" } : { bold: "", plain: s };
    });
}

function parseAnswerBlocks(body: string): Block[] {
  const blocks: Block[] = [];
  for (const raw of String(body ?? "").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const bullet = /^[*\-•]\s+(.*)$/.exec(line);
    const text = bullet ? bullet[1] : line;
    const heading = !bullet && /^\*\*[^*]+\*\*:?$/.test(line);
    blocks.push({ heading, bullet: Boolean(bullet), segs: parseInlineSegs(text) });
  }
  return blocks;
}

// ── 엣지 곡선 (템플릿 edgePath/edgeMid 포팅) ────────────────────────────────

function edgePath(e: ViewEdge, nodeById: Map<string, ViewNode>): string {
  const s = nodeById.get(e.source)!;
  const t = nodeById.get(e.target)!;
  const dx = t.x - s.x, dy = t.y - s.y;
  const len = Math.hypot(dx, dy) || 1;
  const R = 72, ux = dx / len, uy = dy / len;
  const sx = s.x + ux * R, sy = s.y + uy * R, tx = t.x - ux * R, ty = t.y - uy * R;
  const curve = e.dashed ? 44 : Math.max(-54, Math.min(54, (ty - sy) * 0.24));
  const cx1 = sx + (tx - sx) * 0.42, cy1 = sy + curve;
  const cx2 = sx + (tx - sx) * 0.58, cy2 = ty - curve;
  return `M ${sx} ${sy} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${tx} ${ty}`;
}

function edgeMid(e: ViewEdge, nodeById: Map<string, ViewNode>): { x: number; y: number } {
  const s = nodeById.get(e.source)!;
  const t = nodeById.get(e.target)!;
  return { x: (s.x + t.x) / 2, y: (s.y + t.y) / 2 - (e.dashed ? 24 : 12) };
}

// 노드 박스(154px)를 넘는 긴 라벨(정책명 등)은 말줄임 — 전체 이름은 <title> 툴팁과 선택 패널에서.
const LABEL_MAX = 9;
const clipLabel = (label: string) => (label.length > LABEL_MAX ? `${label.slice(0, LABEL_MAX)}…` : label);

// ── 섹션 헤더 공통 ──────────────────────────────────────────────────────────

function SectionIcon({ children }: { children: React.ReactNode }) {
  return (
    <span className="grid h-[30px] w-[30px] flex-none place-items-center rounded-[9px] bg-[#eef3ff] text-[#3f6ede]">
      {children}
    </span>
  );
}

const GraphGlyph = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="6" cy="12" r="2.4" /><circle cx="18" cy="6" r="2.4" /><circle cx="18" cy="18" r="2.4" />
    <path d="M8 11l8-4M8 13l8 4" />
  </svg>
);

// ── 본체 ────────────────────────────────────────────────────────────────────

type Selected = { type: "all" | "node" | "edge"; id: string | null };

export function IndustryReportView({ payload }: { payload: IndustryPayload }) {
  const view = useMemo(() => payloadToView(payload), [payload]);
  const [selected, setSelected] = useState<Selected>({ type: "all", id: null });
  const [active, setActive] = useState<string[]>(view.relations);
  const [search, setSearch] = useState("");

  const nodeById = useMemo(() => new Map(view.nodes.map((n) => [n.id, n])), [view.nodes]);
  const edgeById = useMemo(() => new Map(view.edges.map((e) => [e.id, e])), [view.edges]);
  const activeSet = new Set(active);

  // 선택 → 강조 대상(엣지·노드·근거) 집합 (템플릿 selection() 포팅)
  const { selEdges, selNodes, selEv } = useMemo(() => {
    let selEdges: Set<string>;
    if (selected.type === "edge") selEdges = new Set(selected.id ? [selected.id] : []);
    else if (selected.type === "node")
      selEdges = new Set(view.edges.filter((e) => e.source === selected.id || e.target === selected.id).map((e) => e.id));
    else selEdges = new Set(view.edges.map((e) => e.id));

    let selNodes: Set<string>;
    if (selected.type === "node") {
      selNodes = new Set(selected.id ? [selected.id] : []);
      for (const e of view.edges) {
        if (selEdges.has(e.id)) { selNodes.add(e.source); selNodes.add(e.target); }
      }
    } else if (selected.type === "edge") {
      const e = selected.id ? edgeById.get(selected.id) : undefined;
      selNodes = new Set(e ? [e.source, e.target] : []);
    } else selNodes = new Set(view.nodes.map((n) => n.id));

    let selEv: Set<string>;
    if (selected.type === "edge") {
      const e = selected.id ? edgeById.get(selected.id) : undefined;
      selEv = new Set(e ? e.evidence : []);
    } else if (selected.type === "node")
      selEv = new Set(view.edges.filter((e) => e.source === selected.id || e.target === selected.id).flatMap((e) => e.evidence));
    else selEv = new Set(view.evidence.map((x) => x.id));

    return { selEdges, selNodes, selEv };
  }, [selected, view, edgeById]);

  const counts: Record<string, number> = {};
  for (const e of view.edges) counts[e.relation] = (counts[e.relation] ?? 0) + 1;
  const order = view.relations.length ? view.relations : ["SUPPLIES", "BENEFITS_FROM", "COMPETES_WITH", "COMMUNITY"];

  const toggleRel = (r: string) =>
    setActive((prev) => (prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r]));

  // 선택 패널 문구 (템플릿 그대로)
  let selectionTitle = "전체 경로";
  let selectionDescription =
    "조회 결과에서 생성된 노드와 관계 엣지 전체입니다. 각 엣지는 relation 타입과 연결된 근거 카드로 표시됩니다.";
  if (selected.type === "node" && selected.id) {
    const n = nodeById.get(selected.id);
    if (n) {
      selectionTitle = n.label;
      selectionDescription = "연결된 관계 엣지와 근거 카드가 함께 강조되어 그래프 안에서의 위치를 확인할 수 있습니다.";
    }
  } else if (selected.type === "edge" && selected.id) {
    const e = edgeById.get(selected.id);
    if (e) {
      const s = nodeById.get(e.source), t = nodeById.get(e.target);
      selectionTitle = `${s?.label ?? e.source} → ${t?.label ?? e.target}`;
      selectionDescription = `${relLabel(e.relation)}(${e.relation}) 관계입니다. 이 엣지를 뒷받침하는 공시 문장과 출처 링크가 근거 영역에서 강조됩니다.`;
    }
  }

  const visSel = [...selEdges].filter((id) => {
    const e = edgeById.get(id);
    return e && activeSet.has(e.relation);
  });
  const miniStats = [
    { label: "강조 엣지", value: String(visSel.length) },
    { label: "근거 카드", value: String(selEv.size) },
    { label: "활성 관계", value: String(active.length) },
    { label: "노드 수", value: String(view.nodes.length) },
  ];

  // 근거 목록: 검색은 전체 quote 대상, 카드 표시는 240자 발췌(카드 길이 방지 — 검색 품질 불변)
  const QUOTE_MAX = 240;
  const q = search.trim().toLowerCase();
  const evidenceList = view.evidence.filter(
    (it) =>
      activeSet.has(it.relation) &&
      (!q || [it.id, it.relation, it.title, it.quote, it.source].join(" ").toLowerCase().includes(q)),
  );

  const faith = FAITH_TONE[view.report.faithStatus] ?? FAITH_TONE.unchecked;
  const relationSegments = order.filter((r) => counts[r]);
  const relationSummary = relationSegments.map((r) => `${relLabel(r)} ${counts[r]}`).join(" · ") || "관계 없음";
  const answerBlocks = parseAnswerBlocks(view.report.answerBody);
  const hasGraph = view.nodes.length > 0;

  return (
    <div className="overflow-hidden rounded-[26px] border border-[rgba(20,26,40,0.07)] bg-white text-[#1b1e26] shadow-[0_24px_60px_rgba(20,30,60,0.09),0_2px_6px_rgba(20,30,60,0.04)]">
      {/* HERO */}
      <div
        className="border-b border-[rgba(20,26,40,0.07)] px-6 pb-8 pt-9 sm:px-11"
        style={{
          background:
            "radial-gradient(900px 380px at 6% -30%, rgba(63,110,222,0.14), transparent 60%), linear-gradient(180deg, #eef3ff 0%, #ffffff 62%)",
        }}
      >
        <div className="mb-4 flex flex-wrap items-center gap-2.5">
          <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-[#e6edfd] px-3 text-xs font-extrabold text-[#2b53c0]">
            <GraphGlyph size={13} />
            GraphRAG · Research Report
          </span>
          <span className="text-[13px] font-semibold text-[#9aa1b0]">{view.report.schemaLine}</span>
        </div>
        <h1 className="mb-2.5 text-[30px] font-extrabold leading-[1.12] tracking-[-0.03em] text-[#161922] sm:text-[38px]">
          산업/거시 보고서
        </h1>
        <p className="mb-1 max-w-[760px] break-keep text-[15.5px] font-medium leading-[1.6] text-[#5a6270]">
          {view.report.questionText}
        </p>
        <div className="mt-3.5 flex flex-wrap items-center gap-2 text-[13px] font-semibold text-[#8890a0]">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
            <rect x="3.5" y="5" width="17" height="15" rx="2.4" /><path d="M3.5 9h17M8 3.5v3M16 3.5v3" />
          </svg>
          <span>
            {view.report.generatedMeta} · <span className="text-[#5a6270]">{view.report.questionType}</span> · 조회{" "}
            {view.report.rowCount}행 → 그래프 엣지 <b className="text-[#3a4150]">{view.edges.length}건</b>
          </span>
          <span
            className="inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-[11.5px] font-extrabold"
            style={{ background: faith.bg, color: faith.fg }}
          >
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: faith.dot }} />
            {view.report.faithLabel}
          </span>
        </div>

        {/* METRIC ROW */}
        <div className="mt-6 grid grid-cols-1 gap-3.5 sm:grid-cols-[1.25fr_1fr_1fr]">
          <div className="rounded-2xl border border-[rgba(20,26,40,0.08)] bg-white px-5 py-4 shadow-[0_1px_3px_rgba(20,30,60,0.05)]">
            <div className="text-xs font-extrabold text-[#8890a0]">관계 구성</div>
            {/* 스택바: 실제 관계별 엣지 카운트 비율(목업의 하드코딩 6:1:1 대체) */}
            <div className="my-3 flex h-3 overflow-hidden rounded-full bg-[#eef0f4]">
              {relationSegments.map((r) => (
                <div key={r} style={{ flex: counts[r], background: relColor(r) }} />
              ))}
            </div>
            <div className="flex flex-wrap gap-x-3.5 text-[12.5px] font-bold text-[#5a6270]">{relationSummary}</div>
          </div>
          <div className="rounded-2xl border border-[rgba(20,26,40,0.08)] bg-white px-5 py-4 shadow-[0_1px_3px_rgba(20,30,60,0.05)]">
            <div className="text-xs font-extrabold text-[#8890a0]">그래프 엣지</div>
            <div className="mb-2 mt-2.5 text-[34px] font-extrabold leading-none tracking-[-0.03em] text-[#161922]">
              {view.edges.length}
              <span className="ml-0.5 text-[15px] font-bold text-[#9aa1b0]">건</span>
            </div>
            <div className="text-[12.5px] font-semibold text-[#9aa1b0]">
              노드 {view.nodes.length}개 · Cypher {view.report.attemptCount}회
            </div>
          </div>
          <div className="rounded-2xl border border-[rgba(20,26,40,0.08)] bg-white px-5 py-4 shadow-[0_1px_3px_rgba(20,30,60,0.05)]">
            <div className="text-xs font-extrabold text-[#8890a0]">검증 상태</div>
            <div className="mb-2 mt-2.5 text-[32px] font-extrabold leading-none tracking-[-0.02em]" style={{ color: faith.main }}>
              {faith.short}
            </div>
            <div className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-[#9aa1b0]">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={faith.dot} strokeWidth="2.2" strokeLinecap="round">
                <path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z" />
              </svg>
              {view.report.faithLabel}
            </div>
          </div>
        </div>
      </div>

      {/* ANSWER SUMMARY */}
      <div className="border-b border-[rgba(20,26,40,0.07)] px-6 py-8 sm:px-11">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <SectionIcon>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round">
                <path d="M5 7h14M5 12h14M5 17h9" />
              </svg>
            </SectionIcon>
            <h2 className="text-[17px] font-extrabold tracking-[-0.02em] text-[#161922]">답변 요약</h2>
          </div>
          <span className="inline-flex h-[26px] items-center gap-1.5 rounded-full bg-[#f1f3f7] px-3 text-[11.5px] font-extrabold text-[#7a828f]">
            <span className="h-1.5 w-1.5 rounded-full bg-[#3f6ede]" />
            GraphRAG 생성 · 근거 연결
          </span>
        </div>
        <div className="rounded-[18px] border border-[rgba(20,26,40,0.06)] bg-[#f7f9fc] px-6 py-6">
          <p className="mb-3 break-keep text-[17px] font-bold leading-[1.55] tracking-[-0.01em] text-[#1b1e26]">
            {view.report.answerHeadline}
          </p>
          {/* 마크다운-lite 블록(제목/불릿/문단) — ** 마커 노출 없이 구조화 */}
          <div className="mb-4">
            {answerBlocks.map((b, i) => (
              <p
                key={i}
                className={`relative break-keep font-medium leading-[1.78] ${
                  b.heading ? "mb-1.5 mt-3.5 text-[15px] text-[#1b1e26]" : b.bullet ? "mb-[7px] pl-4 text-[14.5px] text-[#4a515f]" : "mb-2.5 text-[14.5px] text-[#4a515f]"
                }`}
              >
                {b.bullet && <span className="absolute left-0.5 font-extrabold text-[#3f6ede]">·</span>}
                {b.segs.map((s, j) =>
                  s.bold ? (
                    <b key={j} className="font-bold text-[#1b1e26]">{s.bold}</b>
                  ) : (
                    <Fragment key={j}>{s.plain}</Fragment>
                  ),
                )}
              </p>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            {view.report.answerTags.map((tag) => (
              <span
                key={tag}
                className="inline-flex h-[30px] items-center rounded-full border border-[rgba(20,26,40,0.1)] bg-white px-3 text-[13px] font-bold text-[#3a4150]"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* GRAPH */}
      <div className="border-b border-[rgba(20,26,40,0.07)] px-6 py-8 sm:px-11">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <SectionIcon><GraphGlyph /></SectionIcon>
            <div>
              <h2 className="text-[17px] font-extrabold tracking-[-0.02em] text-[#161922]">관계 그래프</h2>
              <div className="mt-0.5 text-[12.5px] font-semibold text-[#9aa1b0]">
                관계 타입과 홉 기반 위치 · 노드·엣지를 눌러 근거를 강조하세요
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {/* 엣지가 없는 관계는 토글할 대상이 없다 — 칩 생략 */}
            {order.filter((r) => counts[r]).map((r) => {
              const isActive = activeSet.has(r);
              return (
                <button
                  key={r}
                  type="button"
                  onClick={() => toggleRel(r)}
                  className="inline-flex h-[34px] cursor-pointer items-center gap-1.5 rounded-full px-3.5 text-[13px] font-extrabold transition-colors"
                  style={{
                    border: `1.5px solid ${isActive ? relColor(r) : "rgba(20,26,40,0.14)"}`,
                    background: isActive ? relSoft(r) : "#ffffff",
                    color: isActive ? relInk(r) : "#8890a0",
                  }}
                >
                  {relLabel(r)}
                  <span className="font-bold opacity-75">{counts[r]}</span>
                </button>
              );
            })}
          </div>
        </div>

        {hasGraph ? (
          <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
            <div
              className="min-h-[470px] overflow-hidden rounded-[18px] border border-[rgba(20,26,40,0.08)]"
              style={{
                backgroundImage: "radial-gradient(rgba(20,30,60,0.055) 1.1px, transparent 1.1px)",
                backgroundSize: "22px 22px",
                backgroundColor: "#fbfcfe",
              }}
            >
              <svg
                viewBox={`0 0 980 ${view.svgHeight}`}
                role="img"
                aria-label="공급망 관계 그래프"
                className="block h-full min-h-[470px] w-full"
                onClick={() => setSelected({ type: "all", id: null })}
              >
                <defs>
                  {[...new Set(view.edges.map((e) => e.relation))].map((r) => (
                    <marker
                      key={r}
                      id={`ar-${r}`}
                      viewBox="0 0 12 12"
                      refX="9"
                      refY="6"
                      markerWidth="8.5"
                      markerHeight="8.5"
                      orient="auto-start-reverse"
                    >
                      <path d="M1 1 L11 6 L1 11 z" fill={relColor(r)} />
                    </marker>
                  ))}
                </defs>
                {view.edges.map((e) => {
                  const vis = activeSet.has(e.relation);
                  const muted = !vis || !selEdges.has(e.id);
                  const activeE = vis && selEdges.has(e.id) && selected.type !== "all";
                  const col = relColor(e.relation);
                  const mid = edgeMid(e, nodeById);
                  const w = Math.max(58, e.label.length * 15 + 22);
                  return (
                    <Fragment key={e.id}>
                      <path
                        d={edgePath(e, nodeById)}
                        strokeDasharray={e.dashed ? "7 7" : undefined}
                        fill="none"
                        stroke={col}
                        strokeWidth={activeE ? 5 : 3}
                        opacity={muted ? 0.12 : 0.85}
                        markerEnd={`url(#ar-${e.relation})`}
                        className="cursor-pointer transition-[opacity,stroke-width] duration-150"
                        onClick={(ev) => {
                          ev.stopPropagation();
                          setSelected({ type: "edge", id: e.id });
                        }}
                      />
                      <g className="pointer-events-none transition-opacity duration-150" opacity={muted ? 0.16 : 1}>
                        <rect x={mid.x - w / 2} y={mid.y - 12} width={w} height={24} rx={12} fill="#fff" stroke="rgba(20,26,40,0.1)" />
                        <text
                          x={mid.x}
                          y={mid.y + 4.5}
                          textAnchor="middle"
                          fill={activeE ? col : "#5a6270"}
                          fontSize="12.5"
                          fontWeight="800"
                        >
                          {e.label}
                        </text>
                      </g>
                    </Fragment>
                  );
                })}
                {view.nodes.map((n) => {
                  const muted = !selNodes.has(n.id);
                  const activeN = selNodes.has(n.id) && selected.type !== "all";
                  const rc = NODE_RING[n.kind] ?? "#c9cdd6";
                  const sf = NODE_SOFT[n.kind] ?? "#f2f4f8";
                  return (
                    <g
                      key={n.id}
                      transform={`translate(${n.x} ${n.y})`}
                      className="cursor-pointer transition-opacity duration-150"
                      opacity={muted ? 0.32 : 1}
                      onClick={(ev) => {
                        ev.stopPropagation();
                        setSelected({ type: "node", id: n.id });
                      }}
                    >
                      <title>{n.label}</title>
                      <rect
                        x={-77}
                        y={-33}
                        width={154}
                        height={66}
                        rx={17}
                        fill="#fff"
                        stroke={activeN ? rc : "rgba(20,26,40,0.12)"}
                        strokeWidth={activeN ? 2.5 : 1.5}
                        style={{ filter: "drop-shadow(0 12px 22px rgba(20,30,55,0.13))" }}
                      />
                      <rect x={-77} y={-33} width={7} height={66} rx={3.5} fill={rc} />
                      <circle cx={-56} cy={0} r={4} fill={sf} stroke={rc} strokeWidth={2} />
                      <text x={-44} y={5} className="pointer-events-none" fill="#161922" fontSize="14.5" fontWeight="800">
                        {clipLabel(n.label)}
                      </text>
                    </g>
                  );
                })}
              </svg>
            </div>
            <aside aria-live="polite" className="flex flex-col rounded-[18px] border border-[rgba(20,26,40,0.06)] bg-[#f7f9fc] p-5">
              <div className="text-[11.5px] font-extrabold uppercase tracking-[0.02em] text-[#8890a0]">선택 항목</div>
              <h3 className="my-2 break-keep text-[19px] font-extrabold tracking-[-0.02em] text-[#161922]">{selectionTitle}</h3>
              <p className="break-keep text-[13.5px] font-medium leading-[1.65] text-[#6a7280]">{selectionDescription}</p>
              <div className="mt-4 grid grid-cols-2 gap-2.5">
                {miniStats.map((m) => (
                  <div key={m.label} className="rounded-xl border border-[rgba(20,26,40,0.07)] bg-white p-3">
                    <span className="block text-[11.5px] font-bold text-[#8890a0]">{m.label}</span>
                    <strong className="mt-1 block text-[22px] font-extrabold tracking-[-0.02em] text-[#161922]">{m.value}</strong>
                  </div>
                ))}
              </div>
            </aside>
          </div>
        ) : (
          <div className="flex items-center gap-3 break-keep rounded-[18px] border border-dashed border-[rgba(20,26,40,0.16)] bg-[#fbfcfe] p-6 text-sm font-semibold leading-[1.6] text-[#6a7280]">
            <span className="flex-none text-[#9aa1b0]"><GraphGlyph size={20} /></span>
            <span>
              이 질문은 공시 원문 검색(벡터) 기반으로 답변되어 관계 그래프 데이터가 없습니다. &ldquo;A 기업의 공급망이
              어디까지 이어지는가&rdquo;처럼 기업 간 관계를 묻는 질문이면 그래프가 생성됩니다.
            </span>
          </div>
        )}
      </div>

      {/* EVIDENCE */}
      <div className="border-b border-[rgba(20,26,40,0.07)] bg-[#f7f9fc] px-6 py-8 sm:px-11">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <SectionIcon>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M9.5 14.5l5-5" />
                <path d="M11 6.5l1-1a3.7 3.7 0 0 1 5.2 5.2l-1 1" />
                <path d="M13 17.5l-1 1a3.7 3.7 0 0 1-5.2-5.2l1-1" />
              </svg>
            </SectionIcon>
            <div>
              <h2 className="text-[17px] font-extrabold tracking-[-0.02em] text-[#161922]">근거 링크</h2>
              <div className="mt-0.5 text-[12.5px] font-semibold text-[#9aa1b0]">그래프 엣지를 뒷받침하는 원문 근거</div>
            </div>
          </div>
          <label className="inline-flex h-10 items-center gap-2 rounded-xl border border-[rgba(20,26,40,0.12)] bg-white px-3.5">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9aa1b0" strokeWidth="2.1" strokeLinecap="round">
              <circle cx="11" cy="11" r="7" /><path d="M20 20l-3.4-3.4" />
            </svg>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="회사명, 관계, 원문 키워드"
              className="w-[220px] border-none bg-transparent text-[13.5px] font-semibold text-[#1b1e26] outline-none"
            />
          </label>
        </div>

        {evidenceList.length > 0 ? (
          <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3">
            {evidenceList.map((it) => {
              const hl = selEv.has(it.id);
              const quoteDisplay = it.quote.length > QUOTE_MAX ? `${it.quote.slice(0, QUOTE_MAX).trimEnd()}…` : it.quote;
              return (
                <article
                  key={it.id}
                  className="flex flex-col gap-3 rounded-2xl bg-white p-[18px]"
                  style={{
                    border: `1px solid ${hl ? relColor(it.relation) : "rgba(20,26,40,0.08)"}`,
                    boxShadow: hl ? `0 0 0 3px ${relSoft(it.relation)}` : "0 1px 3px rgba(20,30,60,0.05)",
                  }}
                >
                  <div className="flex items-center justify-between gap-2.5">
                    <span className="text-[12.5px] font-black tracking-[0.01em] text-[#2b53c0]">[{it.id}]</span>
                    <span
                      className="inline-flex h-6 items-center rounded-full px-2.5 text-[11px] font-black"
                      style={{ background: relSoft(it.relation), color: relInk(it.relation) }}
                    >
                      {relLabel(it.relation)}
                    </span>
                  </div>
                  <h3 className="break-keep text-[15px] font-extrabold leading-[1.4] tracking-[-0.01em] text-[#161922]">
                    {it.title}
                  </h3>
                  <p className="flex-1 break-keep text-[13.5px] font-medium leading-[1.65] text-[#4a515f]">{quoteDisplay}</p>
                  <p className="text-xs font-bold text-[#9aa1b0]">{it.source}</p>
                  {it.hasUrl && (
                    <a
                      href={it.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex h-[34px] w-fit items-center gap-1.5 rounded-[10px] border border-[rgba(20,26,40,0.12)] px-3 text-[12.5px] font-bold text-[#3a4150] transition-colors hover:border-[#2b53c0] hover:text-[#2b53c0]"
                    >
                      원문 열기
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M5 12h14M13 6l6 6-6 6" />
                      </svg>
                    </a>
                  )}
                </article>
              );
            })}
          </div>
        ) : (
          <div className="rounded-2xl border border-[rgba(20,26,40,0.08)] bg-white p-6 text-sm font-semibold text-[#8890a0]">
            현재 필터와 검색어에 맞는 근거가 없습니다.
          </div>
        )}
      </div>

      {/* FOOTER NOTE */}
      <div className="flex items-center gap-2.5 bg-[#f7f9fc] px-6 py-5 text-[12.5px] font-semibold text-[#8890a0] sm:px-11">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#1fb877" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z" /><path d="M9 12l2 2 4-4" />
        </svg>
        <span className="break-keep">
          이 리포트는 공시 원문 그래프에 근거한 자동 분석이며 투자 권유가 아닙니다. 모든 관계는 DART 원문 링크로 검증됩니다.
        </span>
      </div>
    </div>
  );
}
