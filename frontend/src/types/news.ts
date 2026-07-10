// 뉴스 ReportModel — AI news 에이전트가 만들고 backend 가 원본 그대로 저장하는 JSON.
// 출처: supervisor /analyze 의 news 결과 output(= backend news_reports.report_json).
export type NewsGauge = {
  label: string; // 예: "의견 갈림", "긍정 우세"
  score: number; // -1..1
  total: number;
  positive: number;
  neutral: number;
  negative: number;
  positive_pct: number;
  neutral_pct: number;
  negative_pct: number;
};

export type NewsArticle = {
  url: string;
  title: string;
  news_id: number;
  summary: string | null;
  sentiment?: string | null;
};

export type NewsEvent = {
  canonical_id: string;
  canonical_title: string;
  importance: number;
  article_count: number;
  gauge: NewsGauge;
  articles: NewsArticle[];
};

export type NewsDailyCount = { date: string; count: number };

export type NewsReportModel = {
  subject: string;
  generated_at: string;
  period_days: number;
  overall_gauge: NewsGauge;
  top_events: NewsEvent[];
  daily_counts: NewsDailyCount[];
  answer_text: string;
  cited_event_ids: string[];
  evidence_news_ids: number[];
  data_limited: boolean;
  note: string | null;
};

export type NewsReportEnvelope = {
  report_id: string;
  report: NewsReportModel;
};
