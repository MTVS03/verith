/**
 * Stock Resolver 계약 — POST /api/stocks/resolve
 * 정본: backend/src/api/schemas/stock_resolve.py
 * 원문 query 는 응답에 되돌아오지 않는다(§7 보안). 사용자 노출 문구는 프론트가 만든다.
 */

export type MatchType =
  | "stock_code"
  | "stock_name"
  | "alias"
  | "ambiguous_group";

export type ResolveStatus = "resolved" | "ambiguous" | "not_found";

export type ResolveReason =
  | "exact_match"
  | "multiple_stocks"
  | "conflicting_identifiers"
  | "ambiguous_alias"
  | "unknown_identifier"
  | "no_match";

export interface StockResolveRequest {
  query: string; // 1~300자
}

export interface ResolvedStock {
  stock_code: string;
  stock_name: string;
  market: string | null;
}

export interface StockCandidate {
  stock_code: string;
  stock_name: string;
  market: string | null;
  matched_text: string;
  match_type: MatchType;
}

export interface StockResolveResponse {
  status: ResolveStatus;
  reason: ResolveReason;
  stock: ResolvedStock | null;
  candidates: StockCandidate[];
}
