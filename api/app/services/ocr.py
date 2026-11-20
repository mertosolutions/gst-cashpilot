"""Extraction layer (the OCR scanner). Reads an invoice scan into structured fields, validates them with plain code,
and reports which engine did the work.
Engine order: Gemini (multimodal, via the GenAI SDK) when GEMINI_API_KEY is set; otherwise a local parser that works
on PDFs with a text layer. Images need Gemini."""
from __future__ import annotations

import io
import re
import time

from app.core.config import get_settings
from app.models import Business
from app.services import gemini
from app.services.util import GSTIN_RE, parse_date

FIELDS = ["supplier_name", "supplier_gstin", "invoice_no", "invoice_date", "taxable_value", "igst", "cgst", "sgst", "total", "category"]
PROMPT = (
    "You read Indian GST tax invoices. Return ONLY JSON with these keys: supplier_name, supplier_gstin, invoice_no, "
    "invoice_date (YYYY-MM-DD), taxable_value, igst, cgst, sgst, total (numbers, 0 if absent), category (short purchase category, "
    "for example 'Raw material', 'Office supplies', 'Motor car (blocked credit)'), and confidence: an object with the same keys "
    "and a number between 0 and 1 for how sure you are of each value. Also return is_invoice: false if the document is not a supplier invoice at all (for example a tax return summary, statement or report). Also return is_gst_invoice: true only if the document is an Indian GST tax invoice (shows CGST, SGST or IGST), false if it is a VAT or other tax invoice. Do not invent values. Use null when a value is not visible."
)
_AMT = r"(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)"


def _num(s) -> float:
    try:
        return round(float(str(s).replace(",", "")), 2)
    except (TypeError, ValueError):
        return 0.0


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def parse_text(text: str, buyer_gstin: str | None) -> tuple[dict, dict]:
    """Local parser: regular expressions over the text layer. Confidence is 1 when a pattern matched, 0 otherwise."""
    f: dict = {k: None for k in FIELDS}
    gstins = [g for g in re.findall(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b", text)]
    supplier = [g for g in gstins if g != buyer_gstin]
    f["supplier_gstin"] = supplier[0] if supplier else None  # only the business's own GSTIN found: no supplier on this document
    m = re.search(r"Invoice\s*(?:No\.?|Number|#)\s*[:\-]?\s*([A-Za-z0-9/\-]+)", text, re.I)
    f["invoice_no"] = m.group(1) if m and not GSTIN_RE.match(m.group(1)) else None
    m = re.search(r"(?:Invoice\s*)?Date\s*[:\-]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})", text, re.I)
    f["invoice_date"] = m.group(1) if m else None
    for key, pat in (("taxable_value", r"Taxable\s*(?:Value|Amount)"), ("igst", r"IGST(?:\s*@?\s*[\d.]+%)?"), ("cgst", r"CGST(?:\s*@?\s*[\d.]+%)?"),
                     ("sgst", r"SGST(?:\s*@?\s*[\d.]+%)?"), ("total", r"(?:Grand\s*)?Total(?:\s*Amount)?(?:\s*\(incl[^)]*\))?")):
        mm = re.search(pat + r"\s*[:\-]?\s*" + _AMT, text, re.I)
        f[key] = _num(mm.group(1)) if mm else 0.0
    m = re.search(r"(?:Supplier|Seller|Sold by|From)\s*[:\-]?\s*([A-Za-z0-9 &.,'()\-]{3,60})", text, re.I)
    if m:
        f["supplier_name"] = m.group(1).strip()
    else:  # first line that is not a label or a number
        f["supplier_name"] = next((ln.strip() for ln in text.splitlines() if re.search(r"[A-Za-z]{4}", ln) and not re.search(r"invoice|date|gstin|total|tax|bill", ln, re.I)), None)
    m = re.search(r"(?:Category|Nature of supply)\s*[:\-]?\s*([A-Za-z0-9 &/()\-]{3,60})", text, re.I)
    f["category"] = m.group(1).strip() if m else "General purchase"
    f["_flags"] = {"not_invoice": not re.search(r"tax\s+invoice|invoice\s*(?:no|number|#)", text, re.I), "looks_like_return": bool(re.search(r"GSTR-?\s*[123]", text)),
                   "looks_like_vat": bool(re.search(r"\bVAT\b", text)) and not re.search(r"\b(CGST|SGST|IGST)\b", text),
                   "has_gst_terms": bool(re.search(r"\b(GSTIN|CGST|SGST|IGST|GST)\b", text, re.I))}
    conf = {k: (1.0 if f.get(k) not in (None, "", 0.0) else 0.0) for k in FIELDS}
    if f["igst"] or (f["cgst"] and f["sgst"]):  # a head that is legitimately absent is not a low-confidence read
        for k in ("igst", "cgst", "sgst"):
            conf[k] = 1.0
    return f, conf


def validate(fields: dict, business: Business, existing: bool, flags: dict | None = None) -> list[dict]:
    """Plain-code checks that run after the model reads the invoice (the model never decides these)."""
    checks = []
    flags = flags or {}
    tol = get_settings().amount_tolerance
    if flags.get("not_invoice"):
        what = "a GST return summary (GSTR-1, 2B or 3B)" if flags.get("looks_like_return") else "something other than an invoice"
        checks.append({"key": "is_invoice", "label": "Is an invoice", "status": "fail",
                       "detail": f"This document looks like {what}. Upload a supplier's purchase invoice here. GSTR-2B and the purchase register go under Processing layers."})
    if flags.get("looks_like_vat"):
        checks.append({"key": "gst_invoice", "label": "Is a GST tax invoice", "status": "fail",
                       "detail": "This looks like a VAT invoice (no CGST, SGST or IGST). GST credit can only be claimed on a GST tax invoice from a registered supplier."})
    elif flags and not flags.get("has_gst_terms"):
        checks.append({"key": "gst_invoice", "label": "Is a GST tax invoice", "status": "warn", "detail": "No GST wording found on the invoice. Check that it is a GST tax invoice."})
    g = (fields.get("supplier_gstin") or "").strip().upper()
    checks.append({"key": "gstin_format", "label": "Supplier GSTIN format", "status": "ok" if GSTIN_RE.match(g) else "fail",
                   "detail": "Format is valid" if GSTIN_RE.match(g) else "GSTIN must be 15 characters, for example 27ABCDE1234F1Z5"})
    taxable, igst, cgst, sgst = (_num(fields.get(k)) for k in ("taxable_value", "igst", "cgst", "sgst"))
    total = _num(fields.get("total"))
    checks.append({"key": "amounts", "label": "Taxable value is present", "status": "ok" if taxable > 0 else "fail",
                   "detail": "Found" if taxable > 0 else "Taxable value is zero. Enter the value before tax."})
    if total:
        diff = round(taxable + igst + cgst + sgst - total, 2)
        checks.append({"key": "total", "label": "Taxable value + tax = total", "status": "ok" if abs(diff) <= tol else "fail",
                       "detail": "Adds up" if abs(diff) <= tol else f"Off by ₹{abs(diff):,.2f}"})
    else:
        checks.append({"key": "total", "label": "Taxable value + tax = total", "status": "warn", "detail": "Total not found on the invoice"})
    if taxable:
        rate = (igst + cgst + sgst) / taxable * 100
        ok = any(abs(rate - r) <= 0.25 for r in (0, 0.25, 3, 5, 12, 18, 28))
        checks.append({"key": "rate", "label": "GST rate is a standard slab", "status": "ok" if ok else ("fail" if rate > 50 else "warn"),
                       "detail": f"Tax is {rate:.2f}% of taxable value"})
    if len(g) >= 2 and business.gstin[:2]:
        intra = g[:2] == business.gstin[:2]
        good = (intra and igst == 0) or (not intra and cgst == 0 and sgst == 0)
        checks.append({"key": "place", "label": "Tax heads fit the place of supply", "status": "ok" if good else "warn",
                       "detail": ("Same state: CGST + SGST expected" if intra else "Other state: IGST expected") + ("" if good else " (heads look swapped)")})
    try:
        parse_date(fields.get("invoice_date"))
        checks.append({"key": "date", "label": "Invoice date readable", "status": "ok", "detail": str(fields.get("invoice_date"))})
    except Exception:
        checks.append({"key": "date", "label": "Invoice date readable", "status": "fail", "detail": "Could not read the date"})
    if existing:
        checks.append({"key": "dup", "label": "Not already in your books", "status": "warn", "detail": "An invoice with this supplier and number already exists"})
    else:
        checks.append({"key": "dup", "label": "Not already in your books", "status": "ok", "detail": "New invoice"})
    return checks


def extract(data: bytes, content_type: str, filename: str, business: Business) -> dict:
    stages: list[dict] = []
    t0 = time.perf_counter()
    stages.append({"key": "upload", "name": "Upload", "status": "ok", "ms": int((time.perf_counter() - t0) * 1000), "detail": f"{len(data) / 1024:.1f} KB {content_type}"})
    fields: dict = {}
    conf: dict = {}
    gemini_flags: dict = {}
    engine = ""
    notes: list[str] = []
    is_pdf = content_type == "application/pdf" or filename.lower().endswith(".pdf")
    t = time.perf_counter()
    # 1) Google Cloud Document AI (Invoice Parser) reads PDFs and photos. Any failure falls through to the readers below.
    from app.services import document_ai
    if document_ai.enabled():
        try:
            dmime = "application/pdf" if is_pdf else (content_type or "image/jpeg")
            fields, conf = document_ai.extract(data, dmime, business.gstin)
            engine = "Google Cloud Document AI (Invoice Parser)"
            if not (fields.get("invoice_no") and fields.get("supplier_gstin") and fields.get("total")):
                notes.append("Document AI could not read every key field, so the other readers were tried.")
                fields, conf, engine = {}, {}, ""
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Document AI was not used ({type(exc).__name__}); another reader was used.")
            fields, conf, engine = {}, {}, ""
    # Fast path: a PDF with a clean text layer is read locally in milliseconds (no Gemini call, no quota used).
    if is_pdf and not fields:
        try:
            text = _pdf_text(data)
        except Exception:  # noqa: BLE001
            text = ""
        if text.strip():
            lf, lc = parse_text(text, business.gstin)
            flags_l = lf.get("_flags", {})
            tol = get_settings().amount_tolerance
            tax_sum = _num(lf["igst"]) + _num(lf["cgst"]) + _num(lf["sgst"])
            complete = (GSTIN_RE.match(lf.get("supplier_gstin") or "") and lf.get("invoice_no") and lf.get("invoice_date") and _num(lf["taxable_value"]) > 0
                        and _num(lf["total"]) > 0 and abs(_num(lf["taxable_value"]) + tax_sum - _num(lf["total"])) <= tol
                        and not flags_l.get("not_invoice") and not flags_l.get("looks_like_vat"))
            if complete and get_settings().ocr_prefer_local_for_text_pdf:
                fields, conf, engine = lf, lc, "local parser (PDF text layer, fast path)"
    if not fields and gemini.available():
        mime = "application/pdf" if is_pdf else (content_type or "image/jpeg")
        raw = None
        try:  # 1) the Google ADK extraction agent
            import asyncio
            from app.agents.runner import extract_with_agent
            raw = asyncio.run(extract_with_agent(data, mime))
            engine = f"Google ADK extraction_agent + {get_settings().gemini_model}"
        except Exception as exc:  # noqa: BLE001
            if gemini.is_quota_error(exc):
                gemini.mark_quota_hit()
                notes.append("Gemini's free quota is used up, so the local parser was used. Gemini is skipped for 10 minutes.")
            else:
                notes.append(f"ADK agent failed ({type(exc).__name__}); trying the GenAI SDK directly.")
                try:  # 2) direct multimodal call (only for non-quota errors)
                    raw = gemini.generate_json_from_file(data, mime, PROMPT)
                    engine = f"Gemini ({get_settings().gemini_model}) via GenAI SDK"
                except Exception as exc2:  # noqa: BLE001
                    if gemini.is_quota_error(exc2):
                        gemini.mark_quota_hit()
                    notes.append(f"Gemini failed ({type(exc2).__name__}); used the local parser.")
        if raw:
            is_gst = raw.pop("is_gst_invoice", True)
            is_inv = raw.pop("is_invoice", True)
            gemini_flags = {"looks_like_vat": is_gst is False and is_inv is not False, "has_gst_terms": is_gst is not False, "not_invoice": is_inv is False}
            conf = raw.pop("confidence", None) or {}
            fields = {k: raw.get(k) for k in FIELDS}
    if not fields:
        if is_pdf:
            text = _pdf_text(data)
            if not text.strip():
                raise ValueError("This PDF has no text layer (it is a scan). Set GEMINI_API_KEY so Gemini can read it.")
            fields, conf = parse_text(text, business.gstin)
            engine = "local parser (PDF text layer)"
        else:
            if get_settings().gemini_enabled and not gemini.available():
                raise ValueError("Gemini's free quota is used up for now (it resets daily), and photos need Gemini. Upload a PDF with a text layer, or try again later.")
            raise ValueError("Reading photos needs Gemini. Set GEMINI_API_KEY, or upload a PDF with a text layer.")
    stages.append({"key": "read", "name": "Read (OCR)", "status": "ok", "ms": int((time.perf_counter() - t) * 1000), "detail": engine})
    t = time.perf_counter()
    for k in ("taxable_value", "igst", "cgst", "sgst", "total"):
        fields[k] = _num(fields.get(k))
    fields["supplier_gstin"] = (fields.get("supplier_gstin") or "").strip().upper()
    fields["category"] = fields.get("category") or "General purchase"
    try:
        fields["invoice_date"] = parse_date(fields["invoice_date"]).isoformat()
    except Exception:
        pass
    stages.append({"key": "parse", "name": "Structure fields", "status": "ok", "ms": int((time.perf_counter() - t) * 1000), "detail": f"{sum(1 for k in FIELDS if fields.get(k) not in (None, '', 0.0))} of {len(FIELDS)} fields found"})
    flags = fields.pop("_flags", None) or gemini_flags
    return {"fields": fields, "confidence": {k: float(conf.get(k) or 0) for k in FIELDS}, "engine": engine, "stages": stages, "notes": notes, "flags": flags}
