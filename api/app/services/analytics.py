"""Read models for the dashboard, vendor view and the reconciliation drill-down. Everything is computed from the database."""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Gstr2bEntry, ItcCheck, LegalChunk, Match, PurchaseInvoice, Vendor
from app.services import tax
from app.services.itc import claim_deadline
from app.services.util import HEADS, money, month_label, prev_month, rules_config


def available_months(db: Session, business_id: str) -> list[str]:
    a = {r[0] for r in db.query(PurchaseInvoice.month).filter_by(business_id=business_id).distinct()}
    b = {r[0] for r in db.query(Gstr2bEntry.month).filter_by(business_id=business_id).distinct()}
    return sorted(a | b)


def months_window(month: str, n: int) -> list[str]:
    out = [month]
    for _ in range(n - 1):
        out.append(prev_month(out[-1]))
    return list(reversed(out))


def month_metrics(db: Session, business_id: str, month: str) -> dict:
    inv = db.query(func.count(PurchaseInvoice.id), func.coalesce(func.sum(PurchaseInvoice.taxable_value), 0.0),
                   func.coalesce(func.sum(PurchaseInvoice.igst + PurchaseInvoice.cgst + PurchaseInvoice.sgst), 0.0)
                   ).filter_by(business_id=business_id, month=month, confirmed=True).one()
    counts = dict(db.query(Match.match_type, func.count(Match.id)).filter_by(business_id=business_id, month=month).group_by(Match.match_type).all())
    f = tax.figures(db, business_id, month)
    n = int(inv[0])
    matched = counts.get("matched", 0)
    return {
        "month": month, "label": month_label(month), "invoices": n,
        "purchase_taxable": money(inv[1]), "purchase_tax": money(inv[2]), "purchase_total": money(inv[1] + inv[2]),
        "output_tax": f["output_total"], "eligible": f["eligible_total"], "at_risk": f["at_risk_total"], "blocked": f["blocked_total"],
        "cash_safe": f["cash_a"], "cash_full": f["cash_b"], "cash_gap": money(f["cash_a"] - f["cash_b"]),
        "matched": matched, "amount_mismatch": counts.get("amount_mismatch", 0), "missing_in_2b": counts.get("missing_in_2b", 0),
        "missing_in_books": counts.get("missing_in_books", 0),
        "match_rate": round(matched / n * 100, 1) if n else 0.0, "flagged": n - matched,
        "checked": sum(counts.values()) > 0,
    }


def trends(db: Session, business_id: str, month: str, n: int = 6) -> list[dict]:
    return [month_metrics(db, business_id, m) for m in months_window(month, n) if m in set(available_months(db, business_id))]


KPI_DEFS = [
    ("purchase_total", "Total purchase cost", "inr", None, "Intake", "All confirmed purchase invoices including GST"),
    ("output_tax", "Output tax (GST on sales)", "inr", None, "Intake", "GST collected from your customers"),
    ("eligible", "ITC eligible", "inr", "up", "ITC decision", "Credit confirmed by GSTR-2B and safe to claim"),
    ("at_risk", "ITC at risk", "inr", "down", "ITC decision", "Credit not confirmed by the government record"),
    ("blocked", "ITC blocked", "inr", "down", "ITC decision", "Credit that cannot be claimed (Section 17(5) etc.)"),
    ("cash_safe", "Cash payable (safe)", "inr", "down", "Tax and draft", "Output tax minus eligible ITC only"),
    ("cash_full", "Cash if at-risk is claimed", "inr", None, "Tax and draft", "Lower cash now, but a notice risk later"),
    ("match_rate", "Match rate", "pct", "up", "Match", "Invoices matched with GSTR-2B"),
    ("invoices", "Invoices processed", "count", None, "Intake", "Confirmed purchase invoices this month"),
    ("flagged", "Invoices flagged", "count", "down", "Match", "Mismatch or missing in GSTR-2B"),
]


def dashboard_summary(db: Session, business_id: str, month: str) -> dict:
    series = trends(db, business_id, month, 6)
    cur = next((s for s in series if s["month"] == month), month_metrics(db, business_id, month))
    prev_m = prev_month(month)
    prev = next((s for s in series if s["month"] == prev_m), None)
    kpis = []
    for key, label, unit, good, layer, hint in KPI_DEFS:
        v = cur[key]
        p = prev[key] if prev else None
        delta = None if p in (None, 0) else round((v - p) / abs(p) * 100, 1)
        kpis.append({"key": key, "label": label, "unit": unit, "value": v, "previous": p, "delta_pct": delta,
                     "good_when": good, "layer": layer, "hint": hint,
                     "series": [{"month": s["month"], "label": s["label"], "value": s[key]} for s in series]})
    return {"month": month, "label": month_label(month), "checked": cur["checked"], "kpis": kpis, "current": cur}


def _vendor_rows(db: Session, business_id: str, months: list[str]) -> list[dict]:
    invs = db.query(PurchaseInvoice).filter(PurchaseInvoice.business_id == business_id, PurchaseInvoice.month.in_(months), PurchaseInvoice.confirmed.is_(True)).all()
    checks = {c.purchase_invoice_id: c for c in db.query(ItcCheck).filter(ItcCheck.business_id == business_id, ItcCheck.month.in_(months)).all()}
    mt = {m.purchase_invoice_id: m for m in db.query(Match).filter(Match.business_id == business_id, Match.month.in_(months), Match.purchase_invoice_id.isnot(None)).all()}
    extra = {}
    for m, e in db.query(Match, Gstr2bEntry).join(Gstr2bEntry, Match.gstr2b_entry_id == Gstr2bEntry.id).filter(
            Match.business_id == business_id, Match.month.in_(months), Match.match_type == "missing_in_books").all():
        extra[e.supplier_gstin] = extra.get(e.supplier_gstin, 0) + 1
    rows: dict[str, dict] = {}
    for i in invs:
        v = i.vendor
        r = rows.setdefault(v.id, {"vendor_id": v.id, "gstin": v.gstin, "name": v.name, "invoices": 0, "spend": 0.0, "tax": 0.0,
                                  "eligible": 0.0, "at_risk": 0.0, "blocked": 0.0, "issues": 0, "missing_in_2b": 0,
                                  "amount_mismatch": 0, "missing_in_books": extra.get(v.gstin, 0)})
        r["invoices"] += 1
        r["spend"] += i.taxable_value
        r["tax"] += i.tax_total
        c = checks.get(i.id)
        if c:
            r["eligible"] += c.eligible_total
            r["at_risk"] += c.at_risk_total
            r["blocked"] += c.blocked_total
        m = mt.get(i.id)
        if m and m.match_type != "matched":
            r["issues"] += 1
            r[m.match_type] += 1
    total_risk = sum(r["at_risk"] for r in rows.values()) or 0.0
    out = []
    for r in rows.values():
        n = r["invoices"]
        r["matched_pct"] = round((n - r["issues"]) / n * 100, 1) if n else 0.0
        r["share_of_risk"] = round(r["at_risk"] / total_risk * 100, 1) if total_risk else 0.0
        r["risk_level"] = "high" if (r["share_of_risk"] >= 20 or r["matched_pct"] < 70) else "medium" if (r["at_risk"] > 0 or r["issues"] > 0) else "low"
        for k in ("spend", "tax", "eligible", "at_risk", "blocked"):
            r[k] = money(r[k])
        out.append(r)
    return out


SORT_KEYS = {"at_risk", "spend", "invoices", "issues", "matched_pct", "blocked", "eligible", "name"}


def vendors(db: Session, business_id: str, month: str, window: int = 1, sort: str = "at_risk", order: str = "desc",
            limit: int = 8, risk: str | None = None, q: str | None = None) -> dict:
    months = months_window(month, max(1, window))
    rows = _vendor_rows(db, business_id, months)
    total = len(rows)
    if risk:
        rows = [r for r in rows if r["risk_level"] == risk]
    if q:
        rows = [r for r in rows if q.lower() in r["name"].lower() or q.upper() in r["gstin"]]
    sort = sort if sort in SORT_KEYS else "at_risk"
    rows.sort(key=lambda r: (r[sort] if sort != "name" else r["name"].lower()), reverse=(order != "asc"))
    all_risk = sum(r["at_risk"] for r in rows)
    top3 = sum(r["at_risk"] for r in sorted(rows, key=lambda r: r["at_risk"], reverse=True)[:3])
    return {"month": month, "window": window, "months": months, "total_vendors": total, "shown": min(limit, len(rows)),
            "total_at_risk": money(all_risk), "top3_share": round(top3 / all_risk * 100, 1) if all_risk else 0.0,
            "items": rows[:limit] if limit else rows}


def vendor_detail(db: Session, business_id: str, gstin: str, month: str, window: int = 6) -> dict | None:
    v = db.query(Vendor).filter_by(business_id=business_id, gstin=gstin).first()
    if not v:
        return None
    series = []
    for m in months_window(month, window):
        row = next((r for r in _vendor_rows(db, business_id, [m]) if r["gstin"] == gstin), None)
        series.append({"month": m, "label": month_label(m), "spend": row["spend"] if row else 0, "at_risk": row["at_risk"] if row else 0,
                       "blocked": row["blocked"] if row else 0, "matched_pct": row["matched_pct"] if row else None,
                       "invoices": row["invoices"] if row else 0})
    summary = next((r for r in _vendor_rows(db, business_id, months_window(month, window)) if r["gstin"] == gstin), None)
    items = reconciliation_items(db, business_id, month, vendor_gstin=gstin, page_size=50)["items"]
    return {"vendor": {"id": v.id, "gstin": v.gstin, "name": v.name}, "summary": summary, "series": series, "invoices": items}


# ---------- reconciliation (section by section detail) ----------
def _item(m: Match, inv, ent, chk) -> dict:
    vendor = inv.vendor.name if inv else (ent.supplier_name or ent.supplier_gstin)
    gstin = inv.vendor.gstin if inv else ent.supplier_gstin
    status = chk.status if chk else None
    partial = bool(chk and chk.status == "eligible" and chk.at_risk_total > 0)
    return {"match_id": m.id, "invoice_id": inv.id if inv else None, "invoice_no": inv.invoice_no if inv else ent.invoice_no,
            "date": (inv.invoice_date if inv else ent.invoice_date).isoformat(), "vendor": vendor, "gstin": gstin,
            "category": inv.category if inv else None, "taxable": money(inv.taxable_value if inv else ent.taxable_value),
            "tax_books": money(inv.tax_total) if inv else None, "tax_2b": money(ent.tax_total) if ent else None,
            "match_type": m.match_type, "diff": money(m.diff_amount), "itc_status": status, "partial": partial,
            "claimable": chk.eligible_total if chk else 0.0, "at_risk": chk.at_risk_total if chk else 0.0,
            "blocked": chk.blocked_total if chk else 0.0, "rule_key": chk.rule_key if chk else None,
            "citation": chk.citation if chk else None, "source": inv.source if inv else "gstr2b"}


def reconciliation_items(db: Session, business_id: str, month: str, match_type: str | None = None, itc_status: str | None = None,
                         q: str | None = None, vendor_gstin: str | None = None, sort: str = "at_risk", order: str = "desc",
                         page: int = 1, page_size: int = 25) -> dict:
    matches = db.query(Match).filter_by(business_id=business_id, month=month).all()
    invs = {i.id: i for i in db.query(PurchaseInvoice).filter_by(business_id=business_id, month=month).all()}
    ents = {e.id: e for e in db.query(Gstr2bEntry).filter_by(business_id=business_id, month=month).all()}
    checks = {c.match_id: c for c in db.query(ItcCheck).filter_by(business_id=business_id, month=month).all()}
    items = [_item(m, invs.get(m.purchase_invoice_id), ents.get(m.gstr2b_entry_id), checks.get(m.id)) for m in matches]
    counts = {"all": len(items)}
    for t in ("matched", "amount_mismatch", "missing_in_2b", "missing_in_books"):
        counts[t] = sum(1 for i in items if i["match_type"] == t)
    status_counts = {s: sum(1 for i in items if i["itc_status"] == s) for s in ("eligible", "at_risk", "blocked")}
    if match_type:
        items = [i for i in items if i["match_type"] == match_type]
    if itc_status:
        items = [i for i in items if i["itc_status"] == itc_status]
    if vendor_gstin:
        items = [i for i in items if i["gstin"] == vendor_gstin]
    if q:
        ql = q.lower()
        items = [i for i in items if ql in i["vendor"].lower() or ql in i["invoice_no"].lower()]
    keymap = {"at_risk": "at_risk", "claimable": "claimable", "blocked": "blocked", "taxable": "taxable", "date": "date", "vendor": "vendor", "diff": "diff"}
    key = keymap.get(sort, "at_risk")
    items.sort(key=lambda i: (i[key] if not isinstance(i[key], str) else i[key].lower()), reverse=(order != "asc"))
    total = len(items)
    start = (max(1, page) - 1) * page_size
    return {"month": month, "total": total, "page": page, "page_size": page_size, "counts": counts, "status_counts": status_counts,
            "items": items[start:start + page_size]}


def reconciliation_detail(db: Session, business_id: str, match_id: str) -> dict | None:
    m = db.query(Match).filter_by(id=match_id, business_id=business_id).first()
    if not m:
        return None
    inv = db.get(PurchaseInvoice, m.purchase_invoice_id) if m.purchase_invoice_id else None
    ent = db.get(Gstr2bEntry, m.gstr2b_entry_id) if m.gstr2b_entry_id else None
    chk = db.query(ItcCheck).filter_by(match_id=m.id, business_id=business_id).first()
    cfg = rules_config()
    passages = []
    if chk:
        chunks = {c.id: c for c in db.query(LegalChunk).filter(LegalChunk.id.in_(chk.passage_ids or [])).all()}
        for pid, sc in zip(chk.passage_ids or [], chk.passage_scores or []):
            c = chunks.get(pid)
            if c:
                passages.append({"id": c.id, "citation": c.citation, "topic": c.topic, "body": c.body, "score": sc})

    def row(o):
        return None if o is None else {"invoice_no": o.invoice_no, "clean": o.invoice_no_clean, "date": o.invoice_date.isoformat(),
                                       "taxable": o.taxable_value, "igst": o.igst, "cgst": o.cgst, "sgst": o.sgst, "tax_total": o.tax_total}
    books, g2b = row(inv), row(ent)
    book_vendor = inv.vendor if inv else None
    trace = [
        {"layer": 1, "name": "Intake", "status": "ok", "summary": (f"Purchase invoice from the {'scan' if inv and inv.source == 'scan' else 'purchase register'}" if inv else "Entry read from GSTR-2B only")},
        {"layer": 2, "name": "Normalize", "status": "ok", "summary": f"Invoice number cleaned to '{(inv or ent).invoice_no_clean}' for matching"},
        {"layer": 3, "name": "Match", "status": "ok" if m.match_type == "matched" else "warn", "summary": f"Result: {m.match_type.replace('_', ' ')}" + (f" (tax difference ₹{m.diff_amount:,.2f})" if m.match_type == "amount_mismatch" else "")},
    ]
    if chk:
        trace += [
            {"layer": 4, "name": "Rule retrieval (RAG)", "status": "ok" if chk.citation else "warn",
             "summary": (f"Top passage: {chk.citation} (score {chk.passage_scores[0]})" if chk.citation else "No rule found")},
            {"layer": 5, "name": "ITC decision", "status": {"eligible": "ok", "at_risk": "warn", "blocked": "error"}[chk.status],
             "summary": f"{chk.status.replace('_', ' ').title()} by rule '{cfg['rule_labels'].get(chk.rule_key, chk.rule_key)}'"},
            {"layer": 6, "name": "Tax and draft", "status": "ok",
             "summary": f"Adds ₹{chk.eligible_total:,.2f} to eligible ITC, ₹{chk.at_risk_total:,.2f} to at risk, ₹{chk.blocked_total:,.2f} to blocked"}]
    decision = None
    if chk:
        decision = {"status": chk.status, "rule_key": chk.rule_key, "rule_label": cfg["rule_labels"].get(chk.rule_key, chk.rule_key),
                    "reason": chk.reason, "citation": chk.citation, "engine": chk.engine, "llm_explanation": chk.llm_explanation,
                    "claimable": chk.eligible_total, "at_risk": chk.at_risk_total, "blocked": chk.blocked_total,
                    "by_head": {k: {h: getattr(chk, f"{k}_{h}") for h in HEADS} for k in ("eligible", "at_risk", "blocked")},
                    "claim_deadline": claim_deadline(inv.invoice_date).isoformat() if inv else None}
    return {"match": {"id": m.id, "type": m.match_type, "diff": m.diff_amount, "month": m.month},
            "vendor": {"name": (book_vendor.name if book_vendor else (ent.supplier_name if ent else "")), "gstin": (book_vendor.gstin if book_vendor else ent.supplier_gstin)},
            "category": inv.category if inv else None, "invoice_id": inv.id if inv else None, "books": books, "gstr2b": g2b,
            "decision": decision, "passages": passages, "trace": trace}


# ---------- insights ----------
def insights(db: Session, business_id: str, month: str) -> list[dict]:
    out: list[dict] = []
    series = trends(db, business_id, month, 6)
    if not series:
        return out
    cur = series[-1]
    prev = series[-2] if len(series) > 1 else None
    v = vendors(db, business_id, month, window=1, limit=0)
    if cur["at_risk"] > 0:
        pct = round(cur["at_risk"] / cur["eligible"] * 100, 1) if cur["eligible"] else 0
        out.append({"severity": "warn", "layer": "ITC decision", "title": f"₹{cur['at_risk']:,.0f} of credit is not confirmed",
                    "detail": f"That is {pct}% of your eligible ITC. If you claim it and the vendors do not file, cash payable goes up by ₹{cur['cash_gap']:,.0f} later.", "action": "reconciliation"})
    if v["total_at_risk"] > 0 and v["items"]:
        top = sorted(v["items"], key=lambda r: r["at_risk"], reverse=True)[:3]
        names = ", ".join(r["name"] for r in top if r["at_risk"] > 0)
        out.append({"severity": "action", "layer": "Match", "title": f"Call {len([r for r in top if r['at_risk'] > 0])} vendors first",
                    "detail": f"{names} hold {v['top3_share']}% of the at-risk credit this month.", "action": "vendors"})
    if cur["blocked"] > 0:
        n = db.query(ItcCheck).filter_by(business_id=business_id, month=month, status="blocked").count()
        out.append({"severity": "info", "layer": "ITC decision", "title": f"₹{cur['blocked']:,.0f} is blocked under Section 17(5)",
                    "detail": f"{n} invoice(s) are in blocked categories. Do not claim them. Ask your CA if an exception applies.", "action": "reconciliation"})
    if prev and prev["invoices"]:
        d = round(cur["match_rate"] - prev["match_rate"], 1)
        out.append({"severity": "good" if d >= 0 else "warn", "layer": "Match", "title": f"Match rate {'up' if d >= 0 else 'down'} {abs(d)} points",
                    "detail": f"{cur['match_rate']}% this month against {prev['match_rate']}% in {prev['label']}.", "action": "reconciliation"})
    if cur["missing_in_books"]:
        out.append({"severity": "info", "layer": "Match", "title": f"{cur['missing_in_books']} invoice(s) are in GSTR-2B but not in your books",
                    "detail": "Check if you forgot to enter them. Scan the invoice to add it.", "action": "scanner"})
    chronic = []
    for r in v["items"]:
        if r["risk_level"] == "high":
            chronic.append(r["name"])
    if chronic:
        out.append({"severity": "warn", "layer": "Match", "title": "High-risk vendors this month", "detail": ", ".join(chronic[:4]), "action": "vendors"})
    return out
