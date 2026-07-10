import { ResearchView } from "@/features/supervisor/components/research-view";

// supervisor 자연어 질의 창 — 검색 → 5-에이전트 파이프라인 연출 → 리포트 열기.
// 상호작용(상태·타이머)이 있어 뷰 자체는 client component(ResearchView).
export const metadata = {
  title: "veriθ · AI 리서치",
};

export default function ResearchPage() {
  return <ResearchView />;
}
