"""VIEW layer: response and request shapes (what the API returns to the web app)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Me(BaseModel):
    uid: str
    business_id: str
    legal_name: str
    gstin: str
    auth_mode: str


class SeriesPoint(BaseModel):
    month: str
    label: str
    value: float


class Kpi(BaseModel):
    key: str
    label: str
    unit: Literal["inr", "pct", "count"]
    value: float
    previous: float | None
    delta_pct: float | None
    good_when: Literal["up", "down"] | None
    layer: str
    hint: str
    series: list[SeriesPoint]


class MonthMetrics(BaseModel):
    model_config = ConfigDict(extra="allow")
    month: str
    label: str
    invoices: int
    purchase_taxable: float
    purchase_tax: float
    purchase_total: float
    output_tax: float
    eligible: float
    at_risk: float
    blocked: float
    cash_safe: float
    cash_full: float
    cash_gap: float
    matched: int
    amount_mismatch: int
    missing_in_2b: int
    missing_in_books: int
    match_rate: float
    flagged: int
    checked: bool


class DashboardSummary(BaseModel):
    month: str
    label: str
    checked: bool
    kpis: list[Kpi]
    current: MonthMetrics


class Insight(BaseModel):
    severity: Literal["good", "info", "warn", "action"]
    layer: str
    title: str
    detail: str
    action: str


class VendorRow(BaseModel):
    vendor_id: str
    gstin: str
    name: str
    invoices: int
    spend: float
    tax: float
    eligible: float
    at_risk: float
    blocked: float
    issues: int
    missing_in_2b: int
    amount_mismatch: int
    missing_in_books: int
    matched_pct: float
    share_of_risk: float
    risk_level: Literal["low", "medium", "high"]


class VendorList(BaseModel):
    month: str
    window: int
    months: list[str]
    total_vendors: int
    shown: int
    total_at_risk: float
    top3_share: float
    items: list[VendorRow]


class ReconItem(BaseModel):
    match_id: str
    invoice_id: str | None
    invoice_no: str
    date: str
    vendor: str
    gstin: str
    category: str | None
    taxable: float
    tax_books: float | None
    tax_2b: float | None
    match_type: str
    diff: float
    itc_status: str | None
    partial: bool
    claimable: float
    at_risk: float
    blocked: float
    rule_key: str | None
    citation: str | None
    source: str


class ReconList(BaseModel):
    month: str
    total: int
    page: int
    page_size: int
    counts: dict[str, int]
    status_counts: dict[str, int]
    items: list[ReconItem]


class Detail(BaseModel):
    model_config = ConfigDict(extra="allow")


class Stage(BaseModel):
    layer: int
    key: str
    name: str
    description: str
    status: Literal["ok", "warn", "error"]
    duration_ms: int
    items_in: int
    items_out: int
    engine: str
    metrics: dict[str, Any]
    notes: list[str]


class PipelineRunOut(BaseModel):
    id: str
    month: str
    status: str
    total_ms: int
    started_at: str
    finished_at: str | None
    stages: list[Stage]


class Check(BaseModel):
    key: str
    label: str
    status: Literal["ok", "warn", "fail"]
    detail: str


class ScanOut(BaseModel):
    id: str
    filename: str
    status: str
    engine: str | None
    fields: dict[str, Any] | None
    confidence: dict[str, float] | None
    checks: list[Check]
    stages: list[dict[str, Any]]
    notes: list[str] = Field(default_factory=list)
    invoice_id: str | None
    created_at: str


class ScanConfirm(BaseModel):
    supplier_name: str
    supplier_gstin: str
    invoice_no: str
    invoice_date: str
    taxable_value: float
    igst: float = 0
    cgst: float = 0
    sgst: float = 0
    category: str = "General purchase"
    total: float = 0


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    month: str


class SystemStatus(BaseModel):
    api: str
    database: str
    auth_mode: str
    gemini_configured: bool
    gemini_model: str
    embedding_engine: str
    adk_version: str
    rules_indexed: int
    tenant_isolation: str
