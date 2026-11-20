"""Google ADK agents (the agentic layer from the design document).
root_agent routes a request to one specialist: extraction, eligibility or draft. Matching and tax maths are plain Python tools."""
from __future__ import annotations

from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field

from app.agents import tools
from app.core.config import get_settings


class FieldConfidence(BaseModel):
    """0 to 1 per field. A fixed set of keys (the Gemini Developer API does not accept free-form maps)."""
    supplier_name: float = 0
    supplier_gstin: float = 0
    invoice_no: float = 0
    invoice_date: float = 0
    taxable_value: float = 0
    igst: float = 0
    cgst: float = 0
    sgst: float = 0
    total: float = 0
    category: float = 0


class InvoiceFields(BaseModel):
    supplier_name: str | None = None
    supplier_gstin: str | None = None
    invoice_no: str | None = None
    invoice_date: str | None = Field(None, description="YYYY-MM-DD")
    taxable_value: float = 0
    igst: float = 0
    cgst: float = 0
    sgst: float = 0
    total: float = 0
    category: str | None = None
    is_invoice: bool = Field(True, description="false if the document is not a supplier invoice (return summary, statement, report)")
    is_gst_invoice: bool = Field(True, description="false for VAT or non-GST invoices")
    confidence: FieldConfidence = Field(default_factory=FieldConfidence)


def build_agents():
    model = get_settings().gemini_model
    extraction = LlmAgent(
        name="extraction_agent", model=model,
        description="Reads scanned GST invoices using Google Cloud Document AI & Gemini Multimodal OCR schema.",
        instruction=("You read Indian GST tax invoices with high precision. Extract supplier GSTIN, invoice number, date, "
                     "taxable value, CGST, SGST, IGST, and category. Give an accurate confidence score for each field."),
        output_schema=InvoiceFields, disallow_transfer_to_parent=True, disallow_transfer_to_peers=True)

    reconciliation = LlmAgent(
        name="tax_reconciliation_agent", model=model,
        description="Answers questions about GSTR-2B matching, eligible input tax credit (ITC), at-risk amounts, and cash payable.",
        instruction=("You explain reconciliation and tax cash outflow in simple, precise numbers for the business owner. "
                     "Always use the tools: run_matching, get_decision, calculate_cash. "
                     "Present cash payable in both scenarios (Case A: safe eligible credit only; Case B: eligible plus at-risk credit). "
                     "The month is given in session state as {month}."),
        tools=[tools.run_matching, tools.get_decision, tools.calculate_cash])

    vendor_comm = LlmAgent(
        name="vendor_communication_agent", model=model,
        description="Identifies defaulter suppliers blocking credit, lists vendor risks, and triggers automated email compliance notices.",
        instruction=("You specialize in supplier compliance and resolving ITC blocks. "
                     "Use vendor_summary and list_defaulter_vendors to show high-risk suppliers. "
                     "When asked to remind, notify, or email a defaulter vendor, call trigger_vendor_defaulter_notice with the vendor's GSTIN and month. "
                     "The month is given in session state as {month}."),
        tools=[tools.vendor_summary, tools.list_defaulter_vendors, tools.trigger_vendor_defaulter_notice])

    legal_rag = LlmAgent(
        name="gst_legal_rag_agent", model=model,
        description="Answers GST statutory legal questions by querying Vertex AI Search / GCP Managed RAG Engine over Indian GST Acts and Rules.",
        instruction=("You provide authoritative statutory explanations for GST compliance decisions. "
                     "Always search legal passages with search_rules. "
                     "Always cite the exact Section (e.g. Section 16(2)(aa), Section 17(5)) or Rule (Rule 36(4), Rule 88C) returned by the tool. "
                     "Remind the user that this is a pre-filing draft assistant and final filing should be reviewed by a Chartered Accountant."),
        tools=[tools.search_rules])

    root = LlmAgent(
        name="cashpilot_root_agent", model=model,
        description="Root Multi-Agent Orchestrator of GST CashPilot built on Google ADK.",
        instruction=("You are the GST CashPilot Multi-Agent Orchestrator. "
                     "Route questions to the right specialist agent: "
                     "- Tax, credit, 2B matches, cash payable -> tax_reconciliation_agent\n"
                     "- Defaulter suppliers, risk ranking, email notices -> vendor_communication_agent\n"
                     "- GST legal acts, Section 16, Section 17(5) blocked credit -> gst_legal_rag_agent\n"
                     "Always coordinate the response clearly and concisely."),
        sub_agents=[reconciliation, vendor_comm, legal_rag])

    return root, extraction
