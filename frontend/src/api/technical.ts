import type {
  TechnicalChartsReadModel,
  TechnicalReportFollowupsReadModel,
  TechnicalReportReadModel,
  TechnicalTraceDetailReadModel,
} from "@/types/technical";

import { backendFetch } from "./backend";

export async function getTechnicalReport(reportId: string): Promise<TechnicalReportReadModel> {
  return backendFetch<TechnicalReportReadModel>(`/api/technical/reports/${reportId}`);
}

export async function getTechnicalCharts(reportId: string): Promise<TechnicalChartsReadModel> {
  return backendFetch<TechnicalChartsReadModel>(`/api/technical/reports/${reportId}/charts`);
}

export async function getTechnicalTrace(reportId: string): Promise<TechnicalTraceDetailReadModel> {
  return backendFetch<TechnicalTraceDetailReadModel>(`/api/technical/reports/${reportId}/trace`);
}

export async function getTechnicalFollowups(
  reportId: string,
): Promise<TechnicalReportFollowupsReadModel> {
  return backendFetch<TechnicalReportFollowupsReadModel>(
    `/api/technical/reports/${reportId}/followups`,
  );
}
