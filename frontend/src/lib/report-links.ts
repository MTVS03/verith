import type { AgentType, ArchiveItem } from "@/types/archive";

export function frontendReportHref(agentType: AgentType, reportId: string): string | null {
  if (agentType === "technical") return `/reports/technical/${reportId}`;
  return null;
}

export function archiveItemHref(item: ArchiveItem): string | null {
  return frontendReportHref(item.agent_type, item.report_id);
}
