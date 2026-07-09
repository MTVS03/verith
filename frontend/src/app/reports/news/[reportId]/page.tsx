import { AppShell } from "@/components/common/AppShell";
import { NewsReportView } from "@/components/reports/news/NewsReportView";

/**
 * News 리포트 상세. Next 16 App Router: params 는 Promise 이므로 await 한다.
 * 뉴스 리포트는 에이전트가 완성해 준 JSON(ReportModel)을 그대로 렌더한다(재계산 없음).
 */
export default async function NewsReportDetailPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = await params;

  return (
    <AppShell contextLabel="뉴스·심리 리포트">
      <NewsReportView reportId={reportId} />
    </AppShell>
  );
}
