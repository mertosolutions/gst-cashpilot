"""Matching layer: purchase register vs GSTR-2B. Plain Python, exact numbers, no fuzzy matching."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Gstr2bEntry, ItcCheck, Match, PurchaseInvoice
from app.services.util import HEADS, money

MATCH_TYPES = ("matched", "amount_mismatch", "missing_in_2b", "missing_in_books")


def classify(inv: PurchaseInvoice, entry: Gstr2bEntry | None, tol: float) -> tuple[str, float]:
    if entry is None:
        return "missing_in_2b", 0.0
    diff = money(inv.tax_total - entry.tax_total)
    taxable_diff = abs(inv.taxable_value - entry.taxable_value)
    if abs(diff) <= tol and taxable_diff <= tol:
        return "matched", diff
    return "amount_mismatch", diff


def run_matching(db: Session, business_id: str, month: str) -> dict:
    tol = get_settings().amount_tolerance
    invoices = db.query(PurchaseInvoice).filter_by(business_id=business_id, month=month, confirmed=True).all()
    entries = db.query(Gstr2bEntry).filter_by(business_id=business_id, month=month).all()
    db.query(ItcCheck).filter_by(business_id=business_id, month=month).delete(synchronize_session=False)
    db.query(Match).filter_by(business_id=business_id, month=month).delete(synchronize_session=False)

    index: dict[tuple[str, str], list[Gstr2bEntry]] = {}
    for e in entries:
        index.setdefault((e.supplier_gstin, e.invoice_no_clean), []).append(e)
    used: set[str] = set()
    counts = {t: 0 for t in MATCH_TYPES}
    for inv in invoices:
        pool = [e for e in index.get((inv.vendor.gstin, inv.invoice_no_clean), []) if e.id not in used]
        entry = pool[0] if pool else None
        mtype, diff = classify(inv, entry, tol)
        if entry:
            used.add(entry.id)
        counts[mtype] += 1
        db.add(Match(business_id=business_id, month=month, purchase_invoice_id=inv.id,
                     gstr2b_entry_id=entry.id if entry else None, match_type=mtype, diff_amount=diff))
    for e in entries:
        if e.id not in used:
            counts["missing_in_books"] += 1
            db.add(Match(business_id=business_id, month=month, gstr2b_entry_id=e.id, match_type="missing_in_books",
                         diff_amount=e.tax_total))
    db.commit()
    return {"invoices": len(invoices), "entries": len(entries), **counts}
