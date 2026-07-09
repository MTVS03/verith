import { AppShell } from "@/components/ui/app-shell";
import { ArchiveCard } from "@/features/archive/components/archive-card";
import { ArchiveTabs } from "@/features/archive/components/archive-tabs";
import { getArchiveReports } from "@/api/archive";
import type { AgentType } from "@/types/archive";

const DEFAULT_AGENT_TYPE: AgentType = "technical";

export default async function Home({
  searchParams,
}: {
  searchParams?: Promise<{ agent_type?: string }>;
}) {
  const params = (await searchParams) ?? {};
  const agentType = isAgentType(params.agent_type) ? params.agent_type : DEFAULT_AGENT_TYPE;
  const archive = await getArchiveReports({ agentType, limit: 20, offset: 0 });

  return (
    <AppShell
      title="리포트 보관함"
      subtitle="agent_type 기준 공통 카드 리스트입니다. technical 상세 페이지는 바로 연결됩니다."
    >
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <ArchiveTabs active={agentType} />
          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500">
            총 {archive.total}건
          </div>
        </div>

        {archive.items.length ? (
          <div className="grid gap-6 xl:grid-cols-2">
            {archive.items.map((item) => (
              <ArchiveCard key={`${item.agent_type}-${item.report_id}`} item={item} />
            ))}
          </div>
        ) : (
          <div className="rounded-[28px] border border-dashed border-slate-200 bg-white/70 px-6 py-20 text-center text-sm text-slate-400">
            아직 표시할 리포트가 없습니다.
          </div>
        )}
      </div>
    </AppShell>
  );
}

function isAgentType(value?: string): value is AgentType {
  return ["technical", "fundamental", "news", "flow", "industry"].includes(value ?? "");
}
