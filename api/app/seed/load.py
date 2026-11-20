"""Seeds the database through the same intake and pipeline code that real uploads use.
Run:  python -m app.seed.load [--reset]"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

from openpyxl import load_workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR, get_settings
from app.core.database import set_tenant, Base, SessionLocal, engine
from app.models import Business, PurchaseInvoice
from app.seed.generator import BUYER, generate_month, personalize_october, user_profile
from app.services import ingest, pipeline, rag
from app.services.util import clean_invoice_no

SAMPLE_DIR = BASE_DIR / "app/data/sample"
SCAN_DIR = SAMPLE_DIR / "scans"
EARLIER_MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
DEMO_NAME = "Demo Traders Pvt Ltd"


def get_or_create_business(db: Session, uid: str, gstin: str = BUYER, name: str = DEMO_NAME) -> Business:
    b = db.query(Business).filter_by(owner_uid=uid).first()
    if not b:
        b = Business(owner_uid=uid, gstin=gstin, legal_name=name)
        db.add(b)
        db.commit()
    return b


def make_sample_scans() -> list[Path]:
    """Writes 3 sample invoice PDFs derived from the October fixture: one that resolves a 'missing in books' entry,
    one with a wrong total (fails validation) and one new invoice that is not in GSTR-2B."""
    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    reg = {(r["supplier_gstin"], clean_invoice_no(r["invoice_no"])) for r in csv.DictReader(open(SAMPLE_DIR / "purchase_register_oct2026.csv"))}
    ws = load_workbook(SAMPLE_DIR / "GSTR-2B_oct2026_dummy.xlsx")["B2B"]
    rows = [dict(zip([c.value for c in ws[1]], [c.value for c in r])) for r in ws.iter_rows(min_row=2)]
    extras = [r for r in rows if (r["GSTIN of supplier"], clean_invoice_no(r["Invoice number"])) not in reg]

    def pdf(path: Path, vendor: str, gstin: str, no: str, date: str, taxable: float, igst: float, cgst: float, sgst: float, total: float, cat: str):
        c = canvas.Canvas(str(path), pagesize=A4)
        y = 800
        lines = ["TAX INVOICE", f"Supplier: {vendor}", f"GSTIN: {gstin}", f"Invoice No: {no}", f"Invoice Date: {date}",
                 f"Bill to: {DEMO_NAME}", f"Buyer GSTIN: {BUYER}", f"Category: {cat}", "",
                 f"Taxable Value: Rs. {taxable:,.2f}"]
        if igst:
            lines.append(f"IGST @ 18%: Rs. {igst:,.2f}")
        else:
            lines += [f"CGST @ 9%: Rs. {cgst:,.2f}", f"SGST @ 9%: Rs. {sgst:,.2f}"]
        lines.append(f"Total: Rs. {total:,.2f}")
        for i, ln in enumerate(lines):
            c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 16 if i == 0 else 11)
            c.drawString(60, y, ln)
            y -= 26
        c.save()

    made = []
    for idx, (r, bad) in enumerate(zip(extras[:2], (False, True))):
        t, i, cg, sg = (float(r[k]) for k in ("Taxable Value", "Integrated Tax", "Central Tax", "State/UT Tax"))
        total = round(t + i + cg + sg, 2) + (300.0 if bad else 0)
        p = SCAN_DIR / f"scan_{'wrong_total' if bad else 'matches_gstr2b'}_{str(r['Invoice number']).lower()}.pdf"
        pdf(p, r["Trade/Legal name"], r["GSTIN of supplier"], r["Invoice number"], str(r["Invoice Date"])[:10], t, i, cg, sg, total, "General purchase")
        made.append(p)
    made += make_layout_invoices(extras)
    p = SCAN_DIR / "scan_new_invoice_not_in_gstr2b.pdf"
    pdf(p, "Gujarat Chemicals", "24JJJJJ9999J1Z4", "GC/2026/1188", "2026-10-21", 72500.0, 13050.0, 0.0, 0.0, 85550.0, "Raw material")
    made.append(p)
    return made


def _invoice_page(path: Path, *, vendor: str, address: str, gstin: str, no: str, date: str, place: str, items: list[tuple[str, str, int, float]],
                  rate: int, inter_state: bool, category: str) -> None:
    """A fuller GST tax invoice layout: header, supplier and buyer blocks, item table, tax summary."""
    from reportlab.lib import colors
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFillColor(colors.HexColor("#1a73e8")); c.rect(0, h - 70, w, 70, stroke=0, fill=1)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 20); c.drawString(40, h - 45, "TAX INVOICE")
    c.setFont("Helvetica", 9); c.drawRightString(w - 40, h - 45, "Original for recipient")
    c.setFillColor(colors.black); y = h - 100
    for ln, bold in ((f"Supplier: {vendor}", True), (address, False), (f"GSTIN: {gstin}", False), (f"Invoice No: {no}", False), (f"Invoice Date: {date}", False), (f"Place of supply: {place}", False)):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 11); c.drawString(40, y, ln); y -= 17
    c.setFont("Helvetica-Bold", 11); c.drawString(330, h - 100, "Bill to"); c.setFont("Helvetica", 10)
    for i, ln in enumerate((DEMO_NAME, "Andheri East, Mumbai", f"Buyer GSTIN: {BUYER}")):
        c.drawString(330, h - 117 - i * 15, ln)
    y -= 14
    c.setFillColor(colors.HexColor("#e8f0fe")); c.rect(40, y - 4, w - 80, 20, stroke=0, fill=1); c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    for x, t in ((46, "S.No"), (86, "Description"), (300, "HSN"), (370, "Qty"), (420, "Rate"), (500, "Amount")):
        c.drawString(x, y + 2, t)
    y -= 20; c.setFont("Helvetica", 9); taxable = 0.0
    for i, (desc, hsn, qty, rate_) in enumerate(items, 1):
        amt = round(qty * rate_, 2); taxable += amt
        for x, t in ((46, str(i)), (86, desc), (300, hsn), (370, str(qty)), (420, f"{rate_:,.2f}"), (500, f"{amt:,.2f}")):
            c.drawString(x, y, t)
        y -= 18
    c.line(40, y + 8, w - 40, y + 8); y -= 20
    tax = round(taxable * rate / 100, 2)
    lines = [f"Taxable Value: Rs. {taxable:,.2f}"]
    if inter_state:
        lines.append(f"IGST @ {rate}%: Rs. {tax:,.2f}"); total = taxable + tax
    else:
        half = round(tax / 2, 2)
        lines += [f"CGST @ {rate / 2:g}%: Rs. {half:,.2f}", f"SGST @ {rate / 2:g}%: Rs. {half:,.2f}"]; total = taxable + half * 2
    lines.append(f"Total: Rs. {total:,.2f}")
    for i, ln in enumerate(lines):
        c.setFont("Helvetica-Bold" if i == len(lines) - 1 else "Helvetica", 12 if i == len(lines) - 1 else 11); c.drawString(330, y, ln); y -= 20
    c.setFont("Helvetica", 9); c.drawString(40, y - 10, f"Category: {category}")
    c.drawString(40, 60, "Declaration: This is a computer generated sample invoice with made-up data. Not a real tax document.")
    c.save()


def make_layout_invoices(extras: list[dict]) -> list[Path]:
    """Three fuller sample GST invoices: one that matches the third 'missing in books' GSTR-2B entry, one inter-state (IGST), one intra-state at 12%."""
    made = []
    if len(extras) >= 3:
        r = extras[2]
        t = float(r["Taxable Value"]); ig = float(r["Integrated Tax"])
        # rebuild the line items so that qty x rate equals the taxable value of the GSTR-2B entry
        qty = 4
        _invoice_page(SCAN_DIR / "gst_invoice_1_resolves_missing_in_books.pdf", vendor=r["Trade/Legal name"], address="Plot 14, Industrial Area, Maharashtra",
                      gstin=r["GSTIN of supplier"], no=str(r["Invoice number"]), date=str(r["Invoice Date"])[:10], place="27-Maharashtra",
                      items=[("Business supplies, assorted", "4820", qty, round(t / qty, 2))], rate=18, inter_state=ig > 0, category="General purchase")
        made.append(SCAN_DIR / "gst_invoice_1_resolves_missing_in_books.pdf")
    _invoice_page(SCAN_DIR / "gst_invoice_2_igst_not_in_2b.pdf", vendor="Bangalore Components Ltd", address="Peenya Industrial Estate, Bengaluru", gstin="29HHHHH7777H1Z2",
                  no="BCL/26-27/0311", date="2026-10-15", place="27-Maharashtra", items=[("Control boards", "8537", 20, 1800.0), ("Wiring harness", "8544", 30, 450.0)],
                  rate=18, inter_state=True, category="Raw material")
    _invoice_page(SCAN_DIR / "gst_invoice_3_intrastate_12pct_not_in_2b.pdf", vendor="Sunrise Packaging Pvt Ltd", address="MIDC, Navi Mumbai", gstin="27BBBBB1111B1Z6",
                  no="SPK-26-0873", date="2026-10-22", place="27-Maharashtra", items=[("Corrugated boxes 5-ply", "4819", 500, 42.0), ("Packing tape", "3919", 120, 65.0)],
                  rate=12, inter_state=False, category="Packaging")
    made += [SCAN_DIR / "gst_invoice_2_igst_not_in_2b.pdf", SCAN_DIR / "gst_invoice_3_intrastate_12pct_not_in_2b.pdf"]
    return made


def seed(db: Session, uid: str | None = None, reset: bool = False) -> dict:
    s = get_settings()
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    rules = rag.ensure_rules_loaded(db)
    biz = get_or_create_business(db, uid or s.demo_owner_uid)
    set_tenant(db, biz.id)
    if db.query(PurchaseInvoice).filter_by(business_id=biz.id).count():
        return {"seeded": False, "rules": rules}
    owner_uid = uid or s.demo_owner_uid
    # the built-in demo owner keeps the fixed fixtures (the tests and the documents quote them); every other account gets its own numbers
    prof = None if owner_uid == s.demo_owner_uid else user_profile(owner_uid)
    for i, m in enumerate(EARLIER_MONTHS):
        files = generate_month(m, seed=(100 + i) if not prof else prof["seed"] + i, growth=(0.8 + i * 0.05) * (prof["scale"] if prof else 1), vendors=prof["vendors"] if prof else None)
        ingest.ingest_purchase_register(db, biz, files["register"], "register.csv")
        ingest.ingest_gstr2b(db, biz, files["gstr2b"], "gstr2b.xlsx")
        ingest.ingest_sales_summary(db, biz, files["sales"], "sales.csv")
    reg, g2b, sales = ((SAMPLE_DIR / n).read_bytes() for n in ("purchase_register_oct2026.csv", "GSTR-2B_oct2026_dummy.xlsx", "sales_summary_oct2026.csv"))
    if prof:
        reg, g2b, sales = personalize_october(reg, g2b, sales, prof)
    ingest.ingest_purchase_register(db, biz, reg, "purchase_register_oct2026.csv")
    ingest.ingest_gstr2b(db, biz, g2b, "GSTR-2B_oct2026_dummy.xlsx")
    ingest.ingest_sales_summary(db, biz, sales, "sales_summary_oct2026.csv")
    for m in [*EARLIER_MONTHS, "2026-10"]:
        pipeline.run_pipeline(db, biz.id, m)
    make_sample_scans()
    return {"seeded": True, "months": [*EARLIER_MONTHS, "2026-10"], "rules": rules}


if __name__ == "__main__":
    with SessionLocal() as session:
        print(seed(session, reset="--reset" in sys.argv))
