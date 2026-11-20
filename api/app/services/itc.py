"""Decision layer: Eligible / At risk / Blocked for every purchase invoice, with the GST rule found by RAG.
Rule order (same as the ITC decision flowchart in the design document):
  1. not in GSTR-2B           -> At risk
  2. blocked category         -> Blocked
  3. past the claim time limit -> Blocked
  4. books amount > 2B amount -> Eligible up to the 2B amount, the extra is At risk
  5. otherwise                -> Eligible
If no rule passage is found, the result becomes At risk with "no rule found" (it never guesses)."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Gstr2bEntry, ItcCheck, Match, PurchaseInvoice
from app.services import rag
from app.services.util import HEADS, money, month_label, next_month, rules_config

SPLIT_KEYS = ("eligible", "at_risk", "blocked")


def claim_deadline(invoice_date: date) -> date:
    """Section 16(4): 30 November after the end of the financial year of the invoice."""
    fy_end_year = invoice_date.year + 1 if invoice_date.month >= 4 else invoice_date.year
    return date(fy_end_year, 11, 30)


def filing_date(month: str) -> date:
    nm = next_month(month)
    return date(int(nm[:4]), int(nm[5:]), get_settings().return_due_day)


def blocked_tag(category: str) -> str | None:
    cat = (category or "").lower() + " "
    for rule in rules_config()["blocked_categories"]:
        if any(k in cat for k in rule["keywords"]):
            return rule["tag"]
    return None


def _zero() -> dict:
    return {f"{k}_{h}": 0.0 for k in SPLIT_KEYS for h in HEADS}


def _put(out: dict, kind: str, amounts: dict) -> None:
    for h in HEADS:
        out[f"{kind}_{h}"] = money(amounts[h])


def decide(inv: PurchaseInvoice, entry: Gstr2bEntry | None, mtype: str, month: str) -> dict:
    """Pure decision logic. Returns status, rule_key, the amount split by head and the retrieval query."""
    cfg = rules_config()
    books = {h: money(getattr(inv, h)) for h in HEADS}
    amounts = _zero()
    tags: list[str] = []
    tol = get_settings().amount_tolerance
    cat = inv.category or ""
    vendor = inv.vendor.name

    if mtype == "missing_in_2b":
        status, key = "at_risk", "not_in_2b"
        _put(amounts, "at_risk", books)
        reason = (f"{vendor} has not reported invoice {inv.invoice_no} in GSTR-2B for {month_label(month)}. "
                  f"The credit of ₹{sum(books.values()):,.2f} is not confirmed by the government record, so it is at risk.")
    elif entry is not None and not entry.itc_available:
        status, key = "at_risk", "itc_not_available"
        _put(amounts, "at_risk", books)
        reason = "GSTR-2B shows this invoice but marks the ITC as not available, so the credit is at risk."
    elif (tag := blocked_tag(cat)):
        status, key = "blocked", "blocked_category"
        tags = [tag]
        _put(amounts, "blocked", books)
        reason = f"'{cat}' is a blocked category under Section 17(5). The credit of ₹{sum(books.values()):,.2f} cannot be claimed."
    elif filing_date(month) > claim_deadline(inv.invoice_date):
        status, key = "blocked", "too_old"
        _put(amounts, "blocked", books)
        reason = (f"The time limit to claim this credit ended on {claim_deadline(inv.invoice_date):%d %b %Y}. "
                  f"The credit of ₹{sum(books.values()):,.2f} is lost.")
    elif mtype == "amount_mismatch" and entry is not None:
        two_b = {h: money(getattr(entry, h)) for h in HEADS}
        elig = {h: min(books[h], two_b[h]) for h in HEADS}
        extra = {h: max(0.0, money(books[h] - two_b[h])) for h in HEADS}
        _put(amounts, "eligible", elig)
        _put(amounts, "at_risk", extra)
        if sum(extra.values()) > tol:
            status, key = "at_risk" if sum(elig.values()) <= 0 else "eligible", "amount_above_2b"
            reason = (f"Your books show tax ₹{sum(books.values()):,.2f} but GSTR-2B shows ₹{sum(two_b.values()):,.2f}. "
                      f"Only ₹{sum(elig.values()):,.2f} is confirmed. The extra ₹{sum(extra.values()):,.2f} is at risk.")
        else:
            status, key = "eligible", "eligible"
            reason = f"GSTR-2B confirms ₹{sum(elig.values()):,.2f}. The credit can be claimed."
    else:
        status, key = "eligible", "eligible"
        _put(amounts, "eligible", books)
        reason = f"Invoice matches GSTR-2B. The credit of ₹{sum(books.values()):,.2f} can be claimed."

    base_q = cfg["retrieval_queries"].get(key, cfg["retrieval_queries"]["eligible"])
    query = f"{base_q} {cat}" if key == "blocked_category" else base_q
    return {"status": status, "rule_key": key, "amounts": amounts, "reason": reason,
            "query": {"text": query, "tags": [key, *tags]}}


def prepare(db: Session, business_id: str, month: str) -> list[dict]:
    """Layer 5a: apply the decision rules to every invoice (no database writes yet)."""
    matches = db.query(Match).filter(Match.business_id == business_id, Match.month == month,
                                     Match.purchase_invoice_id.isnot(None)).all()
    inv_map = {i.id: i for i in db.query(PurchaseInvoice).filter_by(business_id=business_id, month=month).all()}
    ent_map = {e.id: e for e in db.query(Gstr2bEntry).filter_by(business_id=business_id, month=month).all()}
    out = []
    for m in matches:
        inv = inv_map[m.purchase_invoice_id]
        entry = ent_map.get(m.gstr2b_entry_id) if m.gstr2b_entry_id else None
        d = decide(inv, entry, m.match_type, month)
        d.update(match=m, invoice=inv)
        out.append(d)
    return out


def finalize(db: Session, business_id: str, month: str, decisions: list[dict], retrieved: list[list[dict]]) -> dict:
    """Layer 5b: attach the retrieved rule to each decision and save the ITC checks."""
    min_score = rules_config()["min_rule_score"]
    db.query(ItcCheck).filter_by(business_id=business_id, month=month).delete(synchronize_session=False)
    no_rule = 0
    totals = {"eligible": 0, "at_risk": 0, "blocked": 0}
    for d, passages in zip(decisions, retrieved):
        top = passages[0] if passages and passages[0]["score"] >= min_score else None
        status, key, reason, amounts = d["status"], d["rule_key"], d["reason"], d["amounts"]
        if top is None:
            no_rule += 1
            claimable = {h: sum(amounts[f"{k}_{h}"] for k in SPLIT_KEYS) for h in HEADS}
            amounts = _zero()
            _put(amounts, "at_risk", claimable)
            status, key, reason = "at_risk", "no_rule_found", "No rule found for this case, so the credit is held as at risk. Ask your CA."
        row = ItcCheck(business_id=business_id, month=month, purchase_invoice_id=d["invoice"].id, match_id=d["match"].id,
                       status=status, rule_key=key, reason=reason, citation=top["citation"] if top else None,
                       passage_ids=[p["id"] for p in passages], passage_scores=[p["score"] for p in passages],
                       engine=f"rules+rag({passages[0]['engine']})" if passages else "rules", **amounts)
        db.add(row)
        totals[status] += 1
    db.commit()
    return {"checked": len(decisions), "no_rule_found": no_rule, **totals}


def run_itc(db: Session, business_id: str, month: str) -> dict:
    decisions = prepare(db, business_id, month)
    retrieved = rag.search_many(db, [d["query"] for d in decisions])
    return finalize(db, business_id, month, decisions, retrieved)
