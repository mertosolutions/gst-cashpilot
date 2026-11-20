export type Unit = "inr" | "pct" | "count";
export interface SeriesPoint { month: string; label: string; value: number }
export interface Kpi { key: string; label: string; unit: Unit; value: number; previous: number | null; delta_pct: number | null; good_when: "up" | "down" | null; layer: string; hint: string; series: SeriesPoint[] }
export interface MonthMetrics {
  month: string; label: string; invoices: number; purchase_taxable: number; purchase_tax: number; purchase_total: number; output_tax: number;
  eligible: number; at_risk: number; blocked: number; cash_safe: number; cash_full: number; cash_gap: number;
  matched: number; amount_mismatch: number; missing_in_2b: number; missing_in_books: number; match_rate: number; flagged: number; checked: boolean;
}
export interface DashboardSummary { month: string; label: string; checked: boolean; kpis: Kpi[]; current: MonthMetrics }
export interface Insight { severity: "good" | "info" | "warn" | "action"; layer: string; title: string; detail: string; action: string }
export interface VendorRow {
  vendor_id: string; gstin: string; name: string; invoices: number; spend: number; tax: number; eligible: number; at_risk: number; blocked: number;
  issues: number; missing_in_2b: number; amount_mismatch: number; missing_in_books: number; matched_pct: number; share_of_risk: number; risk_level: "low" | "medium" | "high";
}
export interface VendorList { month: string; window: number; months: string[]; total_vendors: number; shown: number; total_at_risk: number; top3_share: number; items: VendorRow[] }
export interface ReconItem {
  match_id: string; invoice_id: string | null; invoice_no: string; date: string; vendor: string; gstin: string; category: string | null; taxable: number;
  tax_books: number | null; tax_2b: number | null; match_type: MatchType; diff: number; itc_status: ItcStatus | null; partial: boolean; claimable: number; at_risk: number;
  blocked: number; rule_key: string | null; citation: string | null; source: string;
}
export type MatchType = "matched" | "amount_mismatch" | "missing_in_2b" | "missing_in_books";
export type ItcStatus = "eligible" | "at_risk" | "blocked";
export interface ReconList { month: string; total: number; page: number; page_size: number; counts: Record<string, number>; status_counts: Record<string, number>; items: ReconItem[] }
export interface Stage { layer: number; key: string; name: string; description: string; status: "ok" | "warn" | "error"; duration_ms: number; items_in: number; items_out: number; engine: string; metrics: Record<string, number | string>; notes: string[] }
export interface PipelineRun { id: string; month: string; status: string; total_ms: number; started_at: string; finished_at: string | null; stages: Stage[] }
export interface Check { key: string; label: string; status: "ok" | "warn" | "fail"; detail: string }
export interface ScanStage { key: string; name: string; status: string; ms: number; detail: string }
export interface ScanFields { supplier_name: string | null; supplier_gstin: string; invoice_no: string | null; invoice_date: string | null; taxable_value: number; igst: number; cgst: number; sgst: number; total: number; category: string }
export interface Scan { id: string; filename: string; status: string; engine: string | null; fields: ScanFields | null; confidence: Record<string, number> | null; checks: Check[]; stages: ScanStage[]; notes: string[]; invoice_id: string | null; created_at: string }
export interface SystemStatus { api: string; database: string; auth_mode: string; gemini_configured: boolean; gemini_model: string; embedding_engine: string; adk_version: string; rules_indexed: number; tenant_isolation: string }
export interface Me { uid: string; business_id: string; legal_name: string; gstin: string; auth_mode: string }
export type Heads = { igst: number; cgst: number; sgst: number };
export interface Draft {
  month: string; business: { name: string; gstin: string }; disclaimer: string;
  tables: {
    table_3_1: { title: string; taxable_value: number; tax: Heads };
    table_4: { title: string; rows: { label: string; tax: Heads }[] };
    table_6: { title: string; cases: { key: string; label: string; itc_claimed: Heads; cash: Heads; total: number }[] };
    summary: { cash_saved_by_case_b: number; has_sales: boolean };
  };
}
