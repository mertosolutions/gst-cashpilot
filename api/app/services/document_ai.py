"""Google Cloud Document AI (Invoice Parser) for the invoice scanner.
The invoice is sent to the processor, which returns entities (supplier tax id, invoice id, date, net, tax and total amounts) and the OCR text.
GST specific fields (CGST, SGST, IGST) come from the same OCR text with the plain-code parser, and when it finds none the tax is split by place of
supply (same state: CGST + SGST, other state: IGST). If anything fails the caller falls back to the other readers, so the scanner never stops."""
from __future__ import annotations

import base64
import re

from app.core.config import get_settings
from app.services.util import GSTIN_RE


class DocumentAIUnavailable(RuntimeError):
    pass


def _session():
    from app.services import vertex_search
    return vertex_search._session()


def project_id() -> str:
    s = get_settings()
    if s.google_cloud_project:
        return s.google_cloud_project
    try:
        return _session()[1] or ""
    except Exception:  # noqa: BLE001
        return ""


def enabled() -> bool:
    s = get_settings()
    return bool(s.document_ai_enabled and s.document_ai_processor_id)


def _money(entity: dict | None) -> float:
    if not entity:
        return 0.0
    nv = (entity.get("normalizedValue") or {}).get("moneyValue") or {}
    if nv:
        return round(float(nv.get("units", 0) or 0) + float(nv.get("nanos", 0) or 0) / 1e9, 2)
    txt = re.sub(r"[^\d.]", "", entity.get("mentionText") or "")
    try:
        return round(float(txt), 2)
    except ValueError:
        return 0.0


def _date(entity: dict | None) -> str | None:
    if not entity:
        return None
    d = (entity.get("normalizedValue") or {}).get("dateValue")
    if d and d.get("year"):
        return f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}"
    return entity.get("mentionText")


def parse_response(doc: dict, buyer_gstin: str | None) -> tuple[dict, dict]:
    """Processor response -> (fields, confidence) in the scanner's shape."""
    from app.services import ocr
    ents: dict[str, dict] = {}
    for e in doc.get("entities", []):
        t = e.get("type", "")
        if t not in ents or (e.get("confidence", 0) > ents[t].get("confidence", 0)):
            ents[t] = e
    conf_of = lambda *keys: round(max([float(ents[k].get("confidence", 0)) for k in keys if k in ents] or [0.0]), 2)  # noqa: E731
    text = doc.get("text", "")
    lf, _ = ocr.parse_text(text, buyer_gstin)  # GST labels (CGST/SGST/IGST, GSTIN) from the OCR text
    gstin = (ents.get("supplier_tax_id", {}).get("mentionText") or "").replace(" ", "").upper()
    if not GSTIN_RE.match(gstin):
        gstin = lf.get("supplier_gstin") or ""
    taxable = _money(ents.get("net_amount")) or lf.get("taxable_value") or 0.0
    total = _money(ents.get("total_amount")) or lf.get("total") or 0.0
    igst, cgst, sgst = (lf.get(k) or 0.0 for k in ("igst", "cgst", "sgst"))
    if not (igst or cgst or sgst):
        tax = _money(ents.get("total_tax_amount")) or (round(total - taxable, 2) if total and taxable else 0.0)
        if tax > 0:
            if gstin[:2] and buyer_gstin and gstin[:2] != buyer_gstin[:2]:
                igst = tax
            else:
                cgst = sgst = round(tax / 2, 2)
    fields = {
        "supplier_name": ents.get("supplier_name", {}).get("mentionText") or lf.get("supplier_name"),
        "supplier_gstin": gstin or None,
        "invoice_no": (ents.get("invoice_id", {}).get("mentionText") or lf.get("invoice_no") or "").strip() or None,
        "invoice_date": _date(ents.get("invoice_date")) or lf.get("invoice_date"),
        "taxable_value": taxable, "igst": igst, "cgst": cgst, "sgst": sgst, "total": total,
        "category": lf.get("category") or "General purchase",
        "_flags": lf.get("_flags", {}),
    }
    conf = {"supplier_name": conf_of("supplier_name"), "supplier_gstin": conf_of("supplier_tax_id") or (0.8 if gstin else 0.0),
            "invoice_no": conf_of("invoice_id"), "invoice_date": conf_of("invoice_date"), "taxable_value": conf_of("net_amount") or (0.7 if taxable else 0.0),
            "igst": 0.8 if igst else 0.0, "cgst": 0.8 if cgst else 0.0, "sgst": 0.8 if sgst else 0.0, "total": conf_of("total_amount"), "category": 0.6}
    return fields, conf


def extract(data: bytes, mime: str, buyer_gstin: str | None, http=None) -> tuple[dict, dict]:
    s = get_settings()
    project = project_id()
    if not project:
        raise DocumentAIUnavailable("No Google Cloud project is configured")
    sess = http or _session()[0]
    url = (f"https://{s.document_ai_location}-documentai.googleapis.com/v1/projects/{project}/locations/{s.document_ai_location}"
           f"/processors/{s.document_ai_processor_id}:process")
    resp = sess.post(url, json={"rawDocument": {"content": base64.b64encode(data).decode(), "mimeType": mime}}, timeout=60)
    if resp.status_code != 200:
        raise DocumentAIUnavailable(f"Document AI returned {resp.status_code}: {resp.text[:200]}")
    return parse_response(resp.json().get("document", {}), buyer_gstin)
