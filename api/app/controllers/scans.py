"""The OCR scanner: upload an invoice, see the extracted fields with confidence and checks, then confirm."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_business
from app.models import Business, Document, Gstr2bEntry, PurchaseInvoice, Vendor
from app.schemas.views import Detail, ScanConfirm, ScanOut
from app.seed.load import SAMPLE_DIR, SCAN_DIR, make_sample_scans
from app.services import analytics, ocr, pipeline
from app.services.util import clean_invoice_no, month_label, month_of, parse_date

router = APIRouter(prefix="/scans", tags=["scanner"])
MAX_BYTES = 10 * 1024 * 1024


def _out(doc: Document, notes: list[str] | None = None) -> ScanOut:
    return ScanOut(id=doc.id, filename=doc.filename, status=doc.status, engine=doc.engine, fields=doc.extracted.get("fields") if doc.extracted else None,
                   confidence=doc.extracted.get("confidence") if doc.extracted else None, checks=doc.checks or [], stages=doc.stages or [],
                   notes=notes or (doc.extracted or {}).get("notes", []), invoice_id=doc.invoice_id, created_at=doc.created_at.isoformat())


def _exists(db: Session, business_id: str, gstin: str, invoice_no: str) -> bool:
    key = clean_invoice_no(invoice_no)
    return bool(db.query(PurchaseInvoice).join(Vendor).filter(PurchaseInvoice.business_id == business_id, Vendor.gstin == gstin,
                                                              PurchaseInvoice.invoice_no_clean == key).first())


def _process(db: Session, business: Business, data: bytes, filename: str, content_type: str) -> ScanOut:
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File is larger than 10 MB")
    folder = Path(get_settings().upload_dir) / business.id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex[:8]}_{Path(filename).name}"
    path.write_bytes(data)
    doc = Document(business_id=business.id, file_type="invoice_scan", filename=Path(filename).name, content_type=content_type, file_uri=str(path), status="uploaded")
    db.add(doc)
    db.commit()
    try:
        res = ocr.extract(data, content_type, filename, business)
    except ValueError as exc:
        doc.status = "failed"
        doc.stages = [{"key": "read", "name": "Read (OCR)", "status": "fail", "ms": 0, "detail": str(exc)}]
        db.commit()
        raise HTTPException(422, str(exc)) from exc
    f = res["fields"]
    checks = ocr.validate(f, business, _exists(db, business.id, f.get("supplier_gstin", ""), f.get("invoice_no") or ""), res.get("flags"))
    doc.extracted = {"fields": f, "confidence": res["confidence"], "notes": res["notes"], "flags": res.get("flags", {})}
    doc.engine, doc.checks, doc.stages, doc.status = res["engine"], checks, res["stages"] + [
        {"key": "validate", "name": "Validate (code)", "status": "ok" if all(c["status"] == "ok" for c in checks) else "warn", "ms": 1,
         "detail": f"{sum(1 for c in checks if c['status'] == 'ok')} of {len(checks)} checks passed"}], "extracted"
    db.commit()
    return _out(doc)


SAMPLES = [
    ("gst_invoice_1_resolves_missing_in_books.pdf", "Valid GST invoice", "All checks pass. It resolves an entry that is in GSTR-2B but missing from your books."),
    ("scan_wrong_total_x901.pdf", "Invoice with a wrong total", "The total does not add up, so the checks stop it from being saved."),
]


@router.get("/samples")
def samples(business: Business = Depends(get_business)):
    """Two curated sample scans. Any other sample file can still be processed by name."""
    if not (SCAN_DIR / SAMPLES[0][0]).exists():
        make_sample_scans()
    return [{"name": n, "title": t, "description": d} for n, t, d in SAMPLES if (SCAN_DIR / n).exists()]


@router.post("/samples/{name}", response_model=ScanOut)
def run_sample(name: str, db: Session = Depends(get_db), business: Business = Depends(get_business)):
    p = (SCAN_DIR / Path(name).name)
    if not p.exists():
        raise HTTPException(404, "Sample not found")
    return _process(db, business, p.read_bytes(), p.name, "application/pdf")


@router.post("", response_model=ScanOut)
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    data = await file.read()
    # extraction is slow and blocking (Gemini call), so keep it off the event loop
    return await run_in_threadpool(_process, db, business, data, file.filename or "invoice", file.content_type or "application/octet-stream")


@router.get("", response_model=list[ScanOut])
def recent(db: Session = Depends(get_db), business: Business = Depends(get_business)):
    docs = db.query(Document).filter_by(business_id=business.id, file_type="invoice_scan").order_by(Document.created_at.desc()).limit(20).all()
    return [_out(d) for d in docs]


def _checks(db: Session, business: Business, doc: Document, fields: dict) -> list[dict]:
    flags = (doc.extracted or {}).get("flags")
    return ocr.validate(fields, business, _exists(db, business.id, fields["supplier_gstin"].strip().upper(), fields["invoice_no"]), flags)


@router.post("/{doc_id}/validate")
def revalidate(doc_id: str, body: ScanConfirm, db: Session = Depends(get_db), business: Business = Depends(get_business)):
    """Re-runs the plain-code checks on the fields as edited by the user."""
    d = db.query(Document).filter_by(id=doc_id, business_id=business.id).first()
    if not d:
        raise HTTPException(404, "Scan not found")
    return _checks(db, business, d, body.model_dump())


@router.get("/{doc_id}/file")
def file(doc_id: str, db: Session = Depends(get_db), business: Business = Depends(get_business)):
    d = db.query(Document).filter_by(id=doc_id, business_id=business.id).first()
    if not d or not Path(d.file_uri).exists():
        raise HTTPException(404, "File not found")
    return FileResponse(d.file_uri, media_type=d.content_type or None, filename=d.filename)


@router.post("/{doc_id}/confirm", response_model=Detail)
def confirm(doc_id: str, body: ScanConfirm, db: Session = Depends(get_db), business: Business = Depends(get_business)):
    d = db.query(Document).filter_by(id=doc_id, business_id=business.id).first()
    if not d:
        raise HTTPException(404, "Scan not found")
    if d.status == "confirmed":
        raise HTTPException(409, "This scan is already confirmed")
    try:
        dt = parse_date(body.invoice_date)
    except ValueError as exc:
        raise HTTPException(422, "Invoice date is not readable") from exc
    gstin = body.supplier_gstin.strip().upper()
    from app.services.util import valid_gstin
    if not valid_gstin(gstin):
        raise HTTPException(422, "Supplier GSTIN format is invalid")
    if _exists(db, business.id, gstin, body.invoice_no):
        raise HTTPException(409, "An invoice with this supplier and number is already in your books")
    failed = [c for c in _checks(db, business, d, body.model_dump()) if c["status"] == "fail"]
    if failed:
        raise HTTPException(422, "Fix these checks before saving: " + "; ".join(f"{c['label']} ({c['detail']})" for c in failed))
    month = month_of(dt)
    before = analytics.month_metrics(db, business.id, month)
    v = db.query(Vendor).filter_by(business_id=business.id, gstin=gstin).first()
    if not v:
        v = Vendor(business_id=business.id, gstin=gstin, name=body.supplier_name.strip() or gstin)
        db.add(v)
        db.flush()
    inv = PurchaseInvoice(business_id=business.id, vendor_id=v.id, document_id=d.id, month=month, invoice_no=body.invoice_no.strip(),
                          invoice_no_clean=clean_invoice_no(body.invoice_no), invoice_date=dt, taxable_value=body.taxable_value, igst=body.igst,
                          cgst=body.cgst, sgst=body.sgst, category=body.category.strip() or "General purchase", confirmed=True, source="scan")
    db.add(inv)
    db.flush()  # assigns inv.id
    d.status, d.invoice_id = "confirmed", inv.id
    db.commit()
    pipeline.run_pipeline(db, business.id, month)
    after = analytics.month_metrics(db, business.id, month)
    from app.models import ItcCheck, Match
    chk = db.query(ItcCheck).filter_by(business_id=business.id, purchase_invoice_id=inv.id).first()
    m = db.query(Match).filter_by(business_id=business.id, purchase_invoice_id=inv.id).first()
    has_2b = db.query(Gstr2bEntry).filter_by(business_id=business.id, month=month).count() > 0
    warnings = [] if has_2b else [f"There is no GSTR-2B for {month_label(month)} in the app, so every invoice of that month shows as missing in 2B. Upload that month's GSTR-2B under Processing layers."]
    return {"warnings": warnings, "invoice_id": inv.id, "month": month, "match_type": m.match_type if m else None, "itc_status": chk.status if chk else None,
            "reason": chk.reason if chk else None, "citation": chk.citation if chk else None, "before": before, "after": after,
            "impact": {"cash_safe": round(after["cash_safe"] - before["cash_safe"], 2), "at_risk": round(after["at_risk"] - before["at_risk"], 2),
                       "eligible": round(after["eligible"] - before["eligible"], 2)}}


def _remove_scanned_invoice(db: Session, business: Business, d: Document) -> str | None:
    """Removes the invoice that was added from this scan (if any). Returns its month so the layers can be re-run."""
    inv = db.query(PurchaseInvoice).filter_by(document_id=d.id, business_id=business.id, source="scan").first()
    month = inv.month if inv else None
    if inv:
        from app.models import ItcCheck, Match
        db.query(ItcCheck).filter_by(purchase_invoice_id=inv.id).delete(synchronize_session=False)
        db.query(Match).filter_by(purchase_invoice_id=inv.id).delete(synchronize_session=False)
        db.delete(inv)
    return month


@router.post("/{doc_id}/undo", response_model=Detail)
def undo(doc_id: str, db: Session = Depends(get_db), business: Business = Depends(get_business)):
    """Removes an invoice that was added from a scan and runs the processing layers again for its month. The scan stays in the list."""
    d = db.query(Document).filter_by(id=doc_id, business_id=business.id).first()
    if not d or d.status != "confirmed":
        raise HTTPException(404, "This scan is not confirmed")
    month = _remove_scanned_invoice(db, business, d)
    d.status, d.invoice_id = "extracted", None
    db.commit()
    if month:
        pipeline.run_pipeline(db, business.id, month)
    return {"undone": True, "month": month}


@router.delete("/{doc_id}", response_model=Detail)
def delete_scan(doc_id: str, db: Session = Depends(get_db), business: Business = Depends(get_business)):
    """Deletes a scan and its uploaded file. If it was already added to your books, that invoice is removed too and the month is re-processed."""
    d = db.query(Document).filter_by(id=doc_id, business_id=business.id).first()
    if not d:
        raise HTTPException(404, "Scan not found")
    month = _remove_scanned_invoice(db, business, d) if d.status == "confirmed" else None
    try:
        Path(d.file_uri).unlink(missing_ok=True)
    except OSError:
        pass
    db.delete(d)
    db.commit()
    if month:
        pipeline.run_pipeline(db, business.id, month)
    return {"deleted": True, "removed_from_books": month is not None, "month": month}
