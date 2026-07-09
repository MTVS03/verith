/**
 * News Report 계약 — GET /api/news/reports/{id} → { report_id, report: ReportModel }
 * 정본: ai/src/agents/news/schemas/report.py (ReportModel) + backend/src/api/schemas/news_report.py
 *
 * 뉴스 리포트는 **에이전트가 완성해 JSON 으로 준다**(technical 과 달리 backend 는 AI 를 호출하지 않고
 * 이미 완성된 리포트를 저장만 한다). 감성 게이지의 비율·순점수·라벨은 SentimentGauge 의 computed
 * 필드로 **이미 계산돼** 실려 온다 — 프론트는 재계산 없이 그대로 표시한다(가이드라인 §3.2·§7.1).
 */

export interface SentimentGauge {
  // 집계 count (backend 실시간 집계)
  positive: number;
  neutral: number;
  negative: number;
  // 표시용 파생값(dump 에 함께 실림 — 프론트 재계산 불필요)
  total: number;
  positive_pct: number;
  negative_pct: number;
  neutral_pct: number;
  score: number; // -1.0 ~ 1.0
  label: string; // "대체로 긍정" | "대체로 부정" | "의견 갈림" | "데이터 제한"
}

export interface ArticleRef {
  news_id: number;
  summary: string;
  url: string;
  title: string;
  publisher: string | null;
  published_at: string | null;
}

export interface DailyCount {
  date: string; // YYYY-MM-DD
  count: number;
}

export interface ReportEvent {
  canonical_id: string | null;
  canonical_title: string;
  importance: number;
  gauge: SentimentGauge;
  article_count: number;
  articles: ArticleRef[];
}

export interface NewsReportModel {
  subject: string;
  generated_at: string;
  period_days: number | null;
  overall_gauge: SentimentGauge;
  top_events: ReportEvent[];
  daily_counts: DailyCount[];
  answer_text: string;
  cited_event_ids: string[];
  evidence_news_ids: number[];
  data_limited: boolean;
  note: string | null;
}

export interface NewsReportEnvelope {
  report_id: string;
  report: NewsReportModel;
}
