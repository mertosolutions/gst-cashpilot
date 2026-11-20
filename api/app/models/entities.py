"""MODEL layer: ORM entities. These map one to one to the ER diagram in the design document."""
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _id() -> str:
    return str(uuid.uuid4())


class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    owner_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    gstin: Mapped[str] = mapped_column(String(15))
    legal_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (UniqueConstraint("business_id", "gstin"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    gstin: Mapped[str] = mapped_column(String(15))
    name: Mapped[str] = mapped_column(String(200))


class Document(Base):
    """An uploaded file. Invoice scans go through the extraction layer."""
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    file_type: Mapped[str] = mapped_column(String(30))  # invoice_scan | gstr2b | purchase_register | sales_summary
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(100), default="")
    file_uri: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default="uploaded")  # uploaded | extracted | confirmed | failed
    engine: Mapped[str | None] = mapped_column(String(60), nullable=True)
    extracted: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    checks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    stages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    invoice_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PurchaseInvoice(Base):
    __tablename__ = "purchase_invoices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    invoice_no: Mapped[str] = mapped_column(String(60))
    invoice_no_clean: Mapped[str] = mapped_column(String(60), index=True)
    invoice_date: Mapped[date] = mapped_column(Date)
    taxable_value: Mapped[float] = mapped_column(Float)
    igst: Mapped[float] = mapped_column(Float, default=0)
    cgst: Mapped[float] = mapped_column(Float, default=0)
    sgst: Mapped[float] = mapped_column(Float, default=0)
    category: Mapped[str] = mapped_column(String(120), default="General purchase")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(20), default="register")  # register | scan
    vendor: Mapped["Vendor"] = relationship(lazy="joined")

    @property
    def tax_total(self) -> float:
        return round((self.igst or 0) + (self.cgst or 0) + (self.sgst or 0), 2)


class Gstr2bEntry(Base):
    __tablename__ = "gstr2b_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    supplier_gstin: Mapped[str] = mapped_column(String(15), index=True)
    supplier_name: Mapped[str] = mapped_column(String(200), default="")
    invoice_no: Mapped[str] = mapped_column(String(60))
    invoice_no_clean: Mapped[str] = mapped_column(String(60), index=True)
    invoice_date: Mapped[date] = mapped_column(Date)
    taxable_value: Mapped[float] = mapped_column(Float)
    igst: Mapped[float] = mapped_column(Float, default=0)
    cgst: Mapped[float] = mapped_column(Float, default=0)
    sgst: Mapped[float] = mapped_column(Float, default=0)
    itc_available: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def tax_total(self) -> float:
        return round((self.igst or 0) + (self.cgst or 0) + (self.sgst or 0), 2)


class SalesSummary(Base):
    __tablename__ = "sales_summary"
    __table_args__ = (UniqueConstraint("business_id", "month"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    month: Mapped[str] = mapped_column(String(7))
    taxable_value: Mapped[float] = mapped_column(Float)
    igst: Mapped[float] = mapped_column(Float, default=0)
    cgst: Mapped[float] = mapped_column(Float, default=0)
    sgst: Mapped[float] = mapped_column(Float, default=0)


class Match(Base):
    __tablename__ = "matches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    purchase_invoice_id: Mapped[str | None] = mapped_column(ForeignKey("purchase_invoices.id"), nullable=True)
    gstr2b_entry_id: Mapped[str | None] = mapped_column(ForeignKey("gstr2b_entries.id"), nullable=True)
    match_type: Mapped[str] = mapped_column(String(20), index=True)  # matched | amount_mismatch | missing_in_2b | missing_in_books
    diff_amount: Mapped[float] = mapped_column(Float, default=0)


class LegalChunk(Base):
    """GST rule passages used by the RAG layer. Shared by all businesses (no business_id)."""
    __tablename__ = "legal_chunks"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    citation: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)  # pgvector column on AlloyDB
    embed_engine: Mapped[str] = mapped_column(String(60), default="local-hash")


class ItcCheck(Base):
    __tablename__ = "itc_checks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    purchase_invoice_id: Mapped[str] = mapped_column(ForeignKey("purchase_invoices.id"), index=True)
    match_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(20), index=True)  # eligible | at_risk | blocked
    rule_key: Mapped[str] = mapped_column(String(40))
    eligible_igst: Mapped[float] = mapped_column(Float, default=0)
    eligible_cgst: Mapped[float] = mapped_column(Float, default=0)
    eligible_sgst: Mapped[float] = mapped_column(Float, default=0)
    at_risk_igst: Mapped[float] = mapped_column(Float, default=0)
    at_risk_cgst: Mapped[float] = mapped_column(Float, default=0)
    at_risk_sgst: Mapped[float] = mapped_column(Float, default=0)
    blocked_igst: Mapped[float] = mapped_column(Float, default=0)
    blocked_cgst: Mapped[float] = mapped_column(Float, default=0)
    blocked_sgst: Mapped[float] = mapped_column(Float, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    citation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    passage_ids: Mapped[list] = mapped_column(JSON, default=list)
    passage_scores: Mapped[list] = mapped_column(JSON, default=list)
    engine: Mapped[str] = mapped_column(String(60), default="rules+rag")
    llm_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def eligible_total(self) -> float:
        return round(self.eligible_igst + self.eligible_cgst + self.eligible_sgst, 2)

    @property
    def at_risk_total(self) -> float:
        return round(self.at_risk_igst + self.at_risk_cgst + self.at_risk_sgst, 2)

    @property
    def blocked_total(self) -> float:
        return round(self.blocked_igst + self.blocked_cgst + self.blocked_sgst, 2)


class Gstr3bDraft(Base):
    __tablename__ = "gstr3b_drafts"
    __table_args__ = (UniqueConstraint("business_id", "month"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    month: Mapped[str] = mapped_column(String(7))
    tables: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Gstr3bVersion(Base):
    """Version history for GSTR-3B draft filings, tracking adjustments made via Copilot or manual CA edits."""
    __tablename__ = "gstr3b_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str] = mapped_column(String(100), default="v1 (Initial Auto-Draft)")
    change_summary: Mapped[str] = mapped_column(String(300), default="Auto-drafted from reconciled GSTR-2B and purchase register")
    created_by: Mapped[str] = mapped_column(String(100), default="Auto-draft L6")
    tables: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class VendorNotice(Base):
    """Email notices triggered to defaulting vendors whose invoices are missing in GSTR-2B or have amount mismatches."""
    __tablename__ = "vendor_notices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    recipient_email: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="sent")  # sent | delivered | pending
    invoice_count: Mapped[int] = mapped_column(Integer, default=0)
    at_risk_amount: Mapped[float] = mapped_column(Float, default=0.0)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    vendor: Mapped["Vendor"] = relationship(lazy="joined")


class PipelineRun(Base):
    """One run of the processing layers for a month. Powers the processing-layer indicators in the UI."""
    __tablename__ = "pipeline_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    business_id: Mapped[str] = mapped_column(ForeignKey("businesses.id"), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    stages: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_ms: Mapped[int] = mapped_column(Integer, default=0)
