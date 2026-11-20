"""Runs the processing layers for one month and records timings and counts for the UI."""
from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.models.entities import utcnow
from app.models import Gstr2bEntry, PipelineRun, PurchaseInvoice, SalesSummary, Vendor
from app.services import itc, matching, rag, tax
from app.services.util import clean_invoice_no, valid_gstin

LAYERS = [
    (1, "intake", "Intake", "Read GSTR-2B, purchase register and sales totals"),
    (2, "normalize", "Normalize", "Clean invoice numbers and validate GSTINs"),
    (3, "match", "Match", "Match purchase invoices with GSTR-2B"),
    (4, "retrieve", "Rule retrieval (RAG)", "Find the GST rule passage for every case"),
    (5, "decide", "ITC decision", "Eligible, At risk or Blocked with the rule shown"),
    (6, "draft", "Tax and draft", "Cash payable and the GSTR-3B draft"),
]


def _stage(n: int, status: str, ms: float, items_in: int, items_out: int, engine: str, metrics: dict, notes: list[str]) -> dict:
    layer, key, name, desc = LAYERS[n]
    return {"layer": layer, "key": key, "name": name, "description": desc, "status": status,
            "duration_ms": int(ms), "items_in": items_in, "items_out": items_out, "engine": engine,
            "metrics": metrics, "notes": notes}


def run_pipeline(db: Session, business_id: str, month: str) -> PipelineRun:
    run = PipelineRun(business_id=business_id, month=month, status="running", stages=[])
    db.add(run)
    db.commit()
    stages: list[dict] = []
    t_all = time.perf_counter()
    try:
        # L1 intake
        t = time.perf_counter()
        n_inv = db.query(PurchaseInvoice).filter_by(business_id=business_id, month=month, confirmed=True).count()
        n_scan = db.query(PurchaseInvoice).filter_by(business_id=business_id, month=month, source="scan").count()
        n_2b = db.query(Gstr2bEntry).filter_by(business_id=business_id, month=month).count()
        has_sales = db.query(SalesSummary).filter_by(business_id=business_id, month=month).first() is not None
        notes = []
        if not n_2b:
            notes.append("No GSTR-2B entries for this month.")
        if not has_sales:
            notes.append("No sales summary: output tax is taken as zero.")
        stages.append(_stage(0, "warn" if notes else "ok", (time.perf_counter() - t) * 1000, n_inv + n_2b, n_inv + n_2b, "csv/xlsx parsers + Gemini Omni scans",
                             {"purchase_invoices": n_inv, "from_scans": n_scan, "gstr2b_entries": n_2b, "sales_summary": int(has_sales)}, notes))
        # L2 normalize
        t = time.perf_counter()
        invs = db.query(PurchaseInvoice).filter_by(business_id=business_id, month=month, confirmed=True).all()
        changed = sum(1 for i in invs if i.invoice_no_clean != i.invoice_no.upper())
        bad_gstin = [v for v in db.query(Vendor).filter_by(business_id=business_id).all() if not valid_gstin(v.gstin)]
        keys = [(i.vendor.gstin, i.invoice_no_clean) for i in invs]
        dupes = len(keys) - len(set(keys))
        notes = []
        if bad_gstin:
            notes.append(f"{len(bad_gstin)} vendor GSTIN(s) have an invalid format.")
        if dupes:
            notes.append(f"{dupes} duplicate invoice number(s) found.")
        stages.append(_stage(1, "warn" if notes else "ok", (time.perf_counter() - t) * 1000, len(invs), len(invs), "python",
                             {"numbers_cleaned": changed, "invalid_gstin": len(bad_gstin), "duplicates": dupes}, notes))
        # L3 match
        t = time.perf_counter()
        m = matching.run_matching(db, business_id, month)
        stages.append(_stage(2, "ok", (time.perf_counter() - t) * 1000, m["invoices"] + m["entries"], m["matched"] + m["amount_mismatch"] + m["missing_in_2b"] + m["missing_in_books"], "python (exact keys)",
                             {k: m[k] for k in matching.MATCH_TYPES}, []))
        # L4 retrieve
        t = time.perf_counter()
        rules = rag.ensure_rules_loaded(db)
        decisions = itc.prepare(db, business_id, month)
        t_r = time.perf_counter()
        retrieved = rag.search_many(db, [d["query"] for d in decisions])
        stages.append(_stage(3, "ok", (time.perf_counter() - t_r) * 1000, len(decisions), sum(1 for r in retrieved if r), rules["engine"] + " + hybrid tag boost",
                             {"passages_in_index": rules["passages"], "queries": len(decisions), "top_k": 3}, []))
        # L5 decide
        t = time.perf_counter()
        res = itc.finalize(db, business_id, month, decisions, retrieved)
        notes = [f"{res['no_rule_found']} case(s) had no rule: held as at risk."] if res["no_rule_found"] else []
        stages.append(_stage(4, "warn" if notes else "ok", (time.perf_counter() - t) * 1000, len(decisions), res["checked"], "python rules + cited passages",
                             {"eligible": res["eligible"], "at_risk": res["at_risk"], "blocked": res["blocked"], "no_rule_found": res["no_rule_found"]}, notes))
        # L6 draft
        t = time.perf_counter()
        tables = tax.build_draft(db, business_id, month)
        cash_a = sum(tables["table_6"]["cases"][0]["cash"].values())
        stages.append(_stage(5, "ok" if tables["summary"]["has_sales"] else "warn", (time.perf_counter() - t) * 1000, res["checked"], 1, "python (exact maths)",
                             {"cash_payable_safe": round(cash_a, 2), "cash_saved_if_at_risk_claimed": tables["summary"]["cash_saved_by_case_b"]},
                             [] if tables["summary"]["has_sales"] else ["Sales summary missing."]))
        run.status = "warn" if any(s["status"] != "ok" for s in stages) else "ok"
    except Exception as exc:  # noqa: BLE001 - show the failure in the UI
        db.rollback()
        stages.append({"layer": 0, "key": "error", "name": "Error", "description": str(exc), "status": "error", "duration_ms": 0,
                       "items_in": 0, "items_out": 0, "engine": "", "metrics": {}, "notes": [str(exc)]})
        run.status = "error"
    run = db.merge(run)
    run.stages = stages
    run.finished_at = utcnow()
    run.total_ms = int((time.perf_counter() - t_all) * 1000)
    db.commit()
    return run


def latest_run(db: Session, business_id: str, month: str) -> PipelineRun | None:
    return (db.query(PipelineRun).filter_by(business_id=business_id, month=month)
            .order_by(PipelineRun.started_at.desc()).first())


def layer_catalog() -> list[dict]:
    return [{"layer": n, "key": k, "name": nm, "description": d} for n, k, nm, d in LAYERS]
