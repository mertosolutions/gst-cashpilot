"""Draft layer: tax calculation and the GSTR-3B draft (tables 3.1, 4 and 6)."""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Gstr3bDraft, ItcCheck, SalesSummary
from app.services.util import HEADS, money


def cash_payable(output_tax: float, itc: float) -> float:
    """Cash payable = max(0, output tax - ITC claimed), for one tax head. No credit moves between heads."""
    return money(max(0.0, output_tax - itc))


def figures(db: Session, business_id: str, month: str) -> dict:
    sales = db.query(SalesSummary).filter_by(business_id=business_id, month=month).first()
    out = {h: money(getattr(sales, h)) if sales else 0.0 for h in HEADS}
    sums = {}
    for kind in ("eligible", "at_risk", "blocked"):
        cols = [func.coalesce(func.sum(getattr(ItcCheck, f"{kind}_{h}")), 0.0) for h in HEADS]
        row = db.query(*cols).filter(ItcCheck.business_id == business_id, ItcCheck.month == month).one()
        sums[kind] = {h: money(v) for h, v in zip(HEADS, row)}
    case_a = {h: cash_payable(out[h], sums["eligible"][h]) for h in HEADS}
    case_b = {h: cash_payable(out[h], sums["eligible"][h] + sums["at_risk"][h]) for h in HEADS}
    return {
        "sales_taxable": money(sales.taxable_value) if sales else 0.0, "has_sales": sales is not None,
        "output": out, "eligible": sums["eligible"], "at_risk": sums["at_risk"], "blocked": sums["blocked"],
        "case_a": case_a, "case_b": case_b,
        "cash_a": money(sum(case_a.values())), "cash_b": money(sum(case_b.values())),
        "output_total": money(sum(out.values())), "eligible_total": money(sum(sums["eligible"].values())),
        "at_risk_total": money(sum(sums["at_risk"].values())), "blocked_total": money(sum(sums["blocked"].values())),
    }


def build_draft(db: Session, business_id: str, month: str) -> dict:
    f = figures(db, business_id, month)
    tables = {
        "table_3_1": {"title": "3.1 Outward supplies (tax on sales)", "taxable_value": f["sales_taxable"], "tax": f["output"]},
        "table_4": {"title": "4 Eligible ITC",
                    "rows": [
                        {"label": "(A) ITC available - confirmed in GSTR-2B", "tax": f["eligible"]},
                        {"label": "At risk - not confirmed (hold back)", "tax": f["at_risk"]},
                        {"label": "(D) Ineligible ITC - blocked", "tax": f["blocked"]}]},
        "table_6": {"title": "6 Payment of tax",
                    "cases": [
                        {"key": "A", "label": "Case A: claim only Eligible ITC", "itc_claimed": f["eligible"], "cash": f["case_a"], "total": f["cash_a"]},
                        {"key": "B", "label": "Case B: claim Eligible + At risk ITC",
                         "itc_claimed": {h: money(f["eligible"][h] + f["at_risk"][h]) for h in HEADS}, "cash": f["case_b"], "total": f["cash_b"]}]},
        "summary": {"cash_saved_by_case_b": money(f["cash_a"] - f["cash_b"]), "has_sales": f["has_sales"]},
    }
    row = db.query(Gstr3bDraft).filter_by(business_id=business_id, month=month).first() or Gstr3bDraft(business_id=business_id, month=month, tables={})
    row.tables = tables
    db.add(row)
    db.commit()
    return tables
