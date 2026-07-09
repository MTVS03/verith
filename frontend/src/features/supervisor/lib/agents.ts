import {
  ArrowLeftRight,
  Landmark,
  Newspaper,
  Factory,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

import type { AgentType } from "@/types/archive";

// 5개 서브에이전트의 표시 메타. 순서는 목업 typeLabels(재무→기술→뉴스→수급→산업)와 동일.
// 파이프라인 스텝과 완료 후 "리포트 열기" 버튼이 이 메타를 공유한다.
export type AgentMeta = {
  type: AgentType;
  order: number;
  label: string; // 짧은 한글 라벨 (버튼·스텝)
  step: string; // 파이프라인 진행 문구
  desc: string; // 스텝 보조 설명
  icon: LucideIcon;
};

export const AGENT_META: Record<AgentType, AgentMeta> = {
  fundamental: {
    type: "fundamental",
    order: 1,
    label: "재무·펀더멘탈",
    step: "재무 분석",
    desc: "OpenDART 재무제표·컨센서스 대조 중...",
    icon: Landmark,
  },
  technical: {
    type: "technical",
    order: 2,
    label: "가격·기술",
    step: "기술적 분석",
    desc: "KIS 시세로 추세·국면 신호 계산 중...",
    icon: TrendingUp,
  },
  news: {
    type: "news",
    order: 3,
    label: "뉴스·심리",
    step: "뉴스·심리 분석",
    desc: "뉴스 지식그래프에서 이벤트·센티먼트 추적 중...",
    icon: Newspaper,
  },
  flow: {
    type: "flow",
    order: 4,
    label: "수급",
    step: "수급 분석",
    desc: "외국인·기관·개인 매매동향 검증 중...",
    icon: ArrowLeftRight,
  },
  industry: {
    type: "industry",
    order: 5,
    label: "산업·거시",
    step: "산업·거시 분석",
    desc: "산업 지식그래프에서 밸류체인·정책 추론 중...",
    icon: Factory,
  },
};

// 파이프라인 스텝 순서(에이전트). Planning 스텝은 pipeline-box 가 앞에 별도로 붙인다.
export const AGENT_ORDER: AgentType[] = ["fundamental", "technical", "news", "flow", "industry"];

// 리포트 상세 링크 — 지금은 technical 만 실제 페이지가 있다(report-links 와 정합).
// 나머지는 백엔드/프론트 상세가 준비되면 채운다(그때까지 null → 버튼 비활성).
export function agentReportHref(type: AgentType, reportId: string | null): string | null {
  if (!reportId) return null;
  if (type === "technical") return `/reports/technical/${reportId}`;
  if (type === "news") return `/reports/news/${reportId}`;
  return null;
}
