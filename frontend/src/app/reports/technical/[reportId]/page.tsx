import { AppShell } from "@/components/common/AppShell";
import { TechnicalReportView } from "@/components/reports/technical/TechnicalReportView";

/**
 * Technical 리포트 상세. Next 16 App Router: params 는 Promise 이므로 await 한다.
 * 데이터 조회/렌더는 클라이언트 컴포넌트(TechnicalReportView)가 담당한다.
 */
export default async function TechnicalReportDetailPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = await params;

  return (
    <AppShell contextLabel="검증 리포트">
      <TechnicalReportView reportId={reportId} />
    </AppShell>
  );
}
