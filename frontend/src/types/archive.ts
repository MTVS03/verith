export type AgentType =
  | "technical"
  | "fundamental"
  | "news"
  | "flow"
  | "industry";

export type ArchiveCardStock = {
  stock_code: string | null;
  stock_name: string | null;
  market: string | null;
};

export type ArchiveCard = {
  title: string;
  summary: string | null;
  badge_label: string | null;
  badge_value: string | null;
  badge_tone: string | null;
  meta_primary: string | null;
  meta_secondary: string | null;
};

export type ArchiveCardStatus = {
  data_status: string | null;
};

export type ArchiveCardMeta = {
  created_at: string | null;
  as_of: string | null;
  detail_url: string | null;
};

export type ArchiveItem = {
  report_id: string;
  agent_type: AgentType;
  stock: ArchiveCardStock;
  card: ArchiveCard;
  status: ArchiveCardStatus;
  meta: ArchiveCardMeta;
};

export type ArchiveListResponse = {
  items: ArchiveItem[];
  total: number;
  limit: number;
  offset: number;
};
