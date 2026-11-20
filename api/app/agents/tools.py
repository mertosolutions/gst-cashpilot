"""Tools used by the Google ADK agents. They call the same service functions as the REST controllers.
No tool takes a business id from the model: it is read from the ADK session state, which the API sets from the verified token."""
from __future__ import annotations

from google.adk.tools import ToolContext

from app.core.database import SessionLocal, set_tenant
from app.models import ItcCheck, Match, PurchaseInvoice
from app.services import analytics, matching, rag, tax


def _scope(tool_context: ToolContext) -> tuple[str, str]:
    return tool_context.state["business_id"], tool_context.state.get("month", "")


def run_matching(month: str, tool_context: ToolContext) -> dict:
    """Match purchase invoices with GSTR-2B for a month (format YYYY-MM) and return the count of each match type."""
    bid, _ = _scope(tool_context)
    with SessionLocal() as db:
        set_tenant(db, bid)
        return matching.run_matching(db, bid, month)


def get_decision(invoice_no: str, month: str, tool_context: ToolContext) -> dict:
    """Return the ITC decision (status, amounts, reason, cited rule) for one purchase invoice number in a month (YYYY-MM)."""
    bid, _ = _scope(tool_context)
    with SessionLocal() as db:
        set_tenant(db, bid)
        inv = db.query(PurchaseInvoice).filter(PurchaseInvoice.business_id == bid, PurchaseInvoice.month == month,
                                               PurchaseInvoice.invoice_no.ilike(invoice_no)).first()
        if not inv:
            return {"error": f"Invoice {invoice_no} not found for {month}"}
        chk = db.query(ItcCheck).filter_by(business_id=bid, purchase_invoice_id=inv.id).first()
        if not chk:
            return {"error": "ITC check has not been run for this month yet"}
        m = db.get(Match, chk.match_id) if chk.match_id else None
        return {"invoice_no": inv.invoice_no, "vendor": inv.vendor.name, "match": m.match_type if m else None, "status": chk.status,
                "eligible": chk.eligible_total, "at_risk": chk.at_risk_total, "blocked": chk.blocked_total,
                "reason": chk.reason, "rule_citation": chk.citation or "no rule found"}


def search_rules(question: str, tool_context: ToolContext) -> list[dict]:
    """Search the GST rule passages (RAG) and return the top passages with their citations."""
    with SessionLocal() as db:
        return [{"citation": p["citation"], "text": p["body"], "score": p["score"]} for p in rag.search(db, question)]


def vendor_summary(month: str, top_n: int, tool_context: ToolContext) -> dict:
    """List the vendors that block the most credit in a month (YYYY-MM), with at-risk amount and match rate."""
    bid, _ = _scope(tool_context)
    with SessionLocal() as db:
        set_tenant(db, bid)
        v = analytics.vendors(db, bid, month, window=1, sort="at_risk", limit=max(1, min(int(top_n or 5), 20)))
        return {"total_at_risk": v["total_at_risk"], "top3_share_percent": v["top3_share"],
                "vendors": [{k: r[k] for k in ("name", "gstin", "invoices", "at_risk", "blocked", "matched_pct", "risk_level")} for r in v["items"]]}


def calculate_cash(month: str, tool_context: ToolContext) -> dict:
    """Return output tax, eligible, at-risk and blocked ITC and the cash payable in both cases (A: eligible only, B: eligible plus at risk)."""
    bid, _ = _scope(tool_context)
    with SessionLocal() as db:
        set_tenant(db, bid)
        f = tax.figures(db, bid, month)
        return {k: f[k] for k in ("output_total", "eligible_total", "at_risk_total", "blocked_total", "cash_a", "cash_b")}
