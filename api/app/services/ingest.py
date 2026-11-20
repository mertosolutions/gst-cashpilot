"""Intake layer: reads GSTR-2B (xlsx), the purchase register (csv/xlsx) and the sales summary (csv) into the database."""
from __future__ import annotations

import csv
import io
from collections import defaultdict

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.models import Business, Gstr2bEntry, PurchaseInvoice, SalesSummary, Vendor
from app.services.util import clean_invoice_no, month_of, parse_date

REGISTER_COLS = ["invoice_no", "invoice_date", "supplier_gstin", "supplier_name", "taxable_value", "igst", "cgst", "sgst", "category"]


def _num(v) -> float:
    if v in (None, ""):
        return 0.0
    return round(float(str(v).replace(",", "")), 2)


def _vendor(db: Session, business_id: str, gstin: str, name: str, cache: dict) -> Vendor:
    key = gstin.strip().upper()
    v = cache.get(key)
    if v is None:
        v = db.query(Vendor).filter_by(business_id=business_id, gstin=key).first()
        if v is None:
            v = Vendor(business_id=business_id, gstin=key, name=name or key)
            db.add(v)
            db.flush()
        cache[key] = v
    elif name and v.name == v.gstin:
        v.name = name
    return v


def _rows_from_csv(data: bytes) -> list[dict]:
    text = data.decode("utf-8-sig")
    return [{(k or "").strip().lower(): v for k, v in row.items()} for row in csv.DictReader(io.StringIO(text))]


def _rows_from_xlsx(data: bytes, sheet: str | None) -> list[dict]:
    wb = load_workbook(io.BytesIO(data), data_only=True)
    ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h or "").strip().lower() for h in rows[0]]
    return [dict(zip(header, r)) for r in rows[1:] if any(c not in (None, "") for c in r)]


def ingest_purchase_register(db: Session, business: Business, data: bytes, filename: str = "") -> dict:
    rows = _rows_from_xlsx(data, None) if filename.lower().endswith(".xlsx") else _rows_from_csv(data)
    missing = [c for c in REGISTER_COLS if rows and c not in rows[0]]
    if missing:
        raise ValueError(f"Purchase register is missing columns: {', '.join(missing)}")
    months = {month_of(parse_date(r["invoice_date"])) for r in rows}
    db.query(PurchaseInvoice).filter(
        PurchaseInvoice.business_id == business.id, PurchaseInvoice.month.in_(months), PurchaseInvoice.source == "register"
    ).delete(synchronize_session=False)
    cache: dict = {}
    for r in rows:
        d = parse_date(r["invoice_date"])
        v = _vendor(db, business.id, r["supplier_gstin"], r["supplier_name"], cache)
        db.add(PurchaseInvoice(
            business_id=business.id, vendor_id=v.id, month=month_of(d), invoice_no=str(r["invoice_no"]).strip(),
            invoice_no_clean=clean_invoice_no(r["invoice_no"]), invoice_date=d, taxable_value=_num(r["taxable_value"]),
            igst=_num(r["igst"]), cgst=_num(r["cgst"]), sgst=_num(r["sgst"]),
            category=(r.get("category") or "General purchase").strip(), confirmed=True, source="register"))
    db.commit()
    return {"rows": len(rows), "months": sorted(months)}


def _recipient_gstin(data: bytes) -> str | None:
    import re
    from openpyxl import load_workbook
    try:
        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
        for row in ws.iter_rows(values_only=True):
            for v in row:
                if isinstance(v, str) and re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]", v.strip().upper()):
                    return v.strip().upper()
    except Exception:
        return None
    return None


def ingest_gstr2b(db: Session, business: Business, data: bytes, filename: str = "") -> dict:
    rows = _rows_from_xlsx(data, "B2B") if filename.lower().endswith(".xlsx") else _rows_from_csv(data)
    need = ["gstin of supplier", "invoice number", "invoice date", "taxable value", "integrated tax", "central tax", "state/ut tax"]
    missing = [c for c in need if rows and c not in rows[0]]
    if missing:
        raise ValueError(f"GSTR-2B B2B sheet is missing columns: {', '.join(missing)}")
    months = {month_of(parse_date(r["invoice date"])) for r in rows}
    if not business.gstin and filename.lower().endswith(".xlsx"):
        business.gstin = _recipient_gstin(data) or business.gstin  # a new business learns its GSTIN from its own GSTR-2B
    db.query(Gstr2bEntry).filter(Gstr2bEntry.business_id == business.id, Gstr2bEntry.month.in_(months)).delete(synchronize_session=False)
    cache: dict = {}
    for r in rows:
        d = parse_date(r["invoice date"])
        name = str(r.get("trade/legal name") or "")
        _vendor(db, business.id, r["gstin of supplier"], name, cache)
        avail = str(r.get("itc availability") or "Yes").strip().lower() in ("yes", "y", "true", "1", "")
        db.add(Gstr2bEntry(
            business_id=business.id, month=month_of(d), supplier_gstin=str(r["gstin of supplier"]).strip().upper(), supplier_name=name,
            invoice_no=str(r["invoice number"]).strip(), invoice_no_clean=clean_invoice_no(r["invoice number"]), invoice_date=d,
            taxable_value=_num(r["taxable value"]), igst=_num(r["integrated tax"]), cgst=_num(r["central tax"]),
            sgst=_num(r["state/ut tax"]), itc_available=avail))
    db.commit()
    return {"rows": len(rows), "months": sorted(months)}


def ingest_sales_summary(db: Session, business: Business, data: bytes, filename: str = "") -> dict:
    rows = _rows_from_xlsx(data, None) if filename.lower().endswith(".xlsx") else _rows_from_csv(data)
    need = ["month", "taxable_value", "igst", "cgst", "sgst"]
    missing = [c for c in need if rows and c not in rows[0]]
    if missing:
        raise ValueError(f"Sales summary is missing columns: {', '.join(missing)}")
    totals: dict[str, dict] = defaultdict(lambda: dict(taxable_value=0.0, igst=0.0, cgst=0.0, sgst=0.0))
    for r in rows:
        m = str(r["month"]).strip()[:7]
        for k in ("taxable_value", "igst", "cgst", "sgst"):
            totals[m][k] += _num(r[k])
    for m, t in totals.items():
        row = db.query(SalesSummary).filter_by(business_id=business.id, month=m).first() or SalesSummary(business_id=business.id, month=m)
        row.taxable_value, row.igst, row.cgst, row.sgst = (round(t[k], 2) for k in ("taxable_value", "igst", "cgst", "sgst"))
        db.add(row)
    db.commit()
    return {"rows": len(rows), "months": sorted(totals)}
