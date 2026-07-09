/**
 * 공통 리포트 보관함(archive) 계약 — GET /api/reports/archive
 * 정본: backend/src/api/schemas/report_archive.py
 *
 * 여러 agent 리포트를 하나의 공통 카드 리스트로 렌더하기 위한 얇은 계약(agent_type 기준 필터).
 */

export interface ArchiveCardStock {
  stock_code: string | null;
  stock_name: string | null;
  market: string | null;
}

export interface ArchiveCard {
  title: string;
  summary: string | null;
  badge_label: string | null; // 예: "Conf"
  badge_value: string | null; // 예: "84%"
  badge_tone: string | null; // green | amber | red | neutral
  meta_primary: string | null; // 예: final_regime / directional_bias
  meta_secondary: string | null; // 예: 날짜 문자열
}

export interface ArchiveCardStatus {
  data_status: string | null;
}

export interface ArchiveCardMeta {
  created_at: string | null; // ISO datetime
  as_of: string | null;
  detail_url: string | null; // agent 상세 endpoint 경로(없으면 null)
}

export interface ArchiveItem {
  report_id: string;
  agent_type: string;
  stock: ArchiveCardStock;
  card: ArchiveCard;
  status: ArchiveCardStatus;
  meta: ArchiveCardMeta;
}

export interface ArchiveListResponse {
  items: ArchiveItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface ArchiveListParams {
  agent_type?: string;
  client_session_id?: string;
  stock_code?: string;
  limit?: number;
  offset?: number;
}
