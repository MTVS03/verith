import { AppShell } from "@/components/common/AppShell";
import { ResearchScreen } from "@/components/research/ResearchScreen";

export default function Home() {
  return (
    <AppShell contextLabel="AI 분석 리서치">
      <ResearchScreen />
    </AppShell>
  );
}
