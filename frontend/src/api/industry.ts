import { backendFetch } from "./backend";

// research-report.v1 payload — 진실은 ai/src/agents/industry/report_export.py 의 build_report_payload.
// 실 payload 가 필드를 빠뜨릴 수 있어 옵셔널 위주로 선언하고, 뷰(industry-report-view)가 방어한다.
export type IndustryGraphNode = {
  id?: string;
  label?: string;
  type?: string; // Neo4j 라벨: Company·Industry·Policy·Aggregate
  role?: string; // "출발 노드"·"1차 연결"·"정책" 등
  kind?: string; // upstream·midstream·downstream·customer·industry·policy·aggregate
  position?: { x?: number; y?: number };
};

export type IndustryGraphEdge = {
  id?: string;
  source?: string;
  target?: string;
  relation?: string; // SUPPLIES·COMPETES_WITH·BENEFITS_FROM·BELONGS_TO·…
  label?: string;
  style?: string; // "solid" | "dashed"
  evidenceIds?: string[];
};

export type IndustryEvidenceSource = {
  name?: string;
  publisher?: string;
  reportName?: string;
  stockCode?: string;
  url?: string;
  textFragmentUrl?: string;
  section?: string;
  bsnsYear?: string;
};

export type IndustryEvidence = {
  id?: string;
  ref?: string; // "G1" | "V1"
  kind?: string; // "graph" | "vector"
  edgeId?: string;
  relation?: string;
  title?: string;
  quote?: string;
  score?: number;
  source?: IndustryEvidenceSource;
};

export type IndustryPipelineStep = {
  id?: string;
  title?: string;
  status?: string; // "done" | "skipped"
  statusText?: string;
  body?: string;
};

export type IndustryPayload = {
  schemaVersion?: string;
  reportId?: string;
  createdAt?: string;
  locale?: string;
  question?: { text?: string; type?: string; label?: string };
  answer?: {
    headline?: string;
    body?: string;
    tags?: string[];
    faithfulness?: {
      status?: string; // verified | warning | failed | unchecked
      label?: string;
      unsupportedClaims?: { sentence?: string; reason?: string }[];
    };
  };
  metrics?: {
    rows?: number;
    attempts?: number;
    graphEdges?: number;
    graphNodes?: number;
    citations?: number;
  };
  graph?: { nodes?: IndustryGraphNode[]; edges?: IndustryGraphEdge[] };
  evidence?: IndustryEvidence[];
  execution?: { pipeline?: IndustryPipelineStep[]; cypher?: string; retrievalFlow?: string };
  graphSnapshot?: { nodes?: Record<string, number>; relationships?: Record<string, number> };
};

export type IndustryReportEnvelope = {
  report_id: string;
  report: IndustryPayload;
};

// 서버측(상세 페이지 = server component)에서 payload 를 받아 IndustryReportView 가 그린다.
export async function getIndustryReport(reportId: string): Promise<IndustryReportEnvelope> {
  return backendFetch<IndustryReportEnvelope>(`/api/industry/reports/${reportId}`);
}

// DELETE /api/industry/reports/{id} → 204. 브라우저에서 백엔드 직접 호출(backend CORS 허용, technical·news 와 동일).
export async function deleteIndustryReport(reportId: string): Promise<void> {
  await backendFetch<void>(`/api/industry/reports/${reportId}`, { method: "DELETE" });
}

// DELETE /api/industry/reports → industry 리포트 전체 삭제. { deleted: N } 반환.
export async function deleteAllIndustryReports(): Promise<{ deleted: number }> {
  return backendFetch<{ deleted: number }>(`/api/industry/reports`, { method: "DELETE" });
}
