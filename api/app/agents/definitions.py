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
        description="Reads a scanned GST invoice (PDF or photo) into structured fields.",
        instruction=("You read Indian GST tax invoices. Extract the fields exactly as printed. Use null or 0 when a value is not visible. "
                     "Never invent values. Give a confidence between 0 and 1 for every field."),
        output_schema=InvoiceFields, disallow_transfer_to_parent=True, disallow_transfer_to_peers=True)
    eligibility = LlmAgent(
        name="eligibility_agent", model=model,
        description="Answers questions about input tax credit: matching with GSTR-2B, the ITC status of an invoice and the GST rule behind it.",
        instruction=("You explain ITC decisions in simple words for a business owner. Always use the tools; never calculate amounts yourself. "
                     "Quote the rule citation returned by the tool. If a tool says 'no rule found', say so and suggest asking a CA. "
                     "The month is given in session state as {month}. Use YYYY-MM when calling tools."),
        tools=[tools.run_matching, tools.get_decision, tools.search_rules])
    draft = LlmAgent(
        name="draft_agent", model=model,
        description="Answers questions about vendors blocking credit, cash payable and the GSTR-3B draft.",
        instruction=("You explain the cash payable and the vendors who block credit. Always use the tools; the numbers come from the tools only. "
                     "Show both cash cases (A: eligible only, B: eligible plus at risk) when asked about cash. Nothing is filed: this is a draft for a CA to review. "
                     "The month is given in session state as {month}."),
        tools=[tools.vendor_summary, tools.calculate_cash])
    root = LlmAgent(
        name="cashpilot_root_agent", model=model,
        description="Root agent of GST CashPilot.",
        instruction=("You are GST CashPilot, a pre-filing GST assistant. Send ITC and invoice questions to eligibility_agent and vendor, "
                     "cash and GSTR-3B questions to draft_agent. You never file returns and you never give final tax advice."),
        sub_agents=[eligibility, draft])
    return root, extraction
