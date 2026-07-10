import type { AgentType, ArchiveItem } from "@/types/archive";

export function frontendReportHref(agentType: AgentType, reportId: string): string | null {
  if (agentType === "technical") return `/reports/technical/${reportId}`;
  if (agentType === "news") return `/reports/news/${reportId}`;
  if (agentType === "industry") return `/reports/industry/${reportId}`;
  if (agentType === "fundamental") return `/reports/fundamental/${reportId}`;
  if (agentType === "flow") return `/reports/flow/${reportId}`;
  return null;
}

export function archiveItemHref(item: ArchiveItem): string | null {
  return frontendReportHref(item.agent_type, item.report_id);
}
