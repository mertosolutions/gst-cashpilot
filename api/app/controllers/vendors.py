from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.controllers.common import month_param
from app.core.database import get_db
from app.core.security import get_business
from app.models import Business, Vendor, VendorNotice
from app.schemas.views import Detail, VendorList
from app.services import analytics

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("", response_model=VendorList)
def list_vendors(month: str = Depends(month_param), window: int = Query(1, ge=1, le=12, description="months to look back, ending at `month`"),
                 sort: str = "at_risk", order: Literal["asc", "desc"] = "desc", limit: int = Query(8, ge=0, le=100), offset: int = Query(0, ge=0),
                 risk: Literal["low", "medium", "high"] | None = None, q: str | None = None,
                 db: Session = Depends(get_db), business: Business = Depends(get_business)):
    return analytics.vendors(db, business.id, month, window, sort, order, limit, risk, q, offset)


@router.get("/notices/all", response_model=Detail)
def all_notices(month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    notices = db.query(VendorNotice).filter_by(business_id=business.id, month=month).order_by(VendorNotice.sent_at.desc()).all()
    return {
        "month": month,
        "count": len(notices),
        "notices": [
            {
                "id": n.id,
                "vendor_id": n.vendor_id,
                "vendor_name": n.vendor.name if n.vendor else "Unknown",
                "vendor_gstin": n.vendor.gstin if n.vendor else "",
                "recipient_email": n.recipient_email,
                "subject": n.subject,
                "body": n.body,
                "status": n.status,
                "invoice_count": n.invoice_count,
                "at_risk_amount": n.at_risk_amount,
                "sent_at": n.sent_at.isoformat() if n.sent_at else "",
            }
            for n in notices
        ],
    }


@router.get("/{gstin}", response_model=Detail)
def vendor(gstin: str, month: str = Depends(month_param), window: int = Query(6, ge=1, le=12),
           db: Session = Depends(get_db), business: Business = Depends(get_business)):
    d = analytics.vendor_detail(db, business.id, gstin.upper(), month, window)
    if not d:
        raise HTTPException(404, "Vendor not found")
    notices = db.query(VendorNotice).join(Vendor).filter(Vendor.business_id == business.id, Vendor.gstin == gstin.upper(), VendorNotice.month == month).all()
    d["notices"] = [
        {"id": n.id, "subject": n.subject, "recipient_email": n.recipient_email, "sent_at": n.sent_at.isoformat(), "status": n.status, "at_risk_amount": n.at_risk_amount}
        for n in notices
    ]
    return d


def _generate_notice(vendor_name: str, vendor_gstin: str, business: Business, month: str, at_risk_invoices: list[dict], custom_note: str | None = None) -> tuple[str, str, float]:
    total_at_risk = sum(float(inv.get("at_risk") or inv.get("tax_total") or 0) for inv in at_risk_invoices)
    subject = f"URGENT: GSTR-1 Non-Filing / ITC Discrepancy Notice for {month} - {business.legal_name}"
    
    inv_lines = []
    for inv in at_risk_invoices:
        inv_no = inv.get("invoice_no") or "N/A"
        inv_dt = inv.get("invoice_date") or ""
        val = float(inv.get("taxable_value") or 0)
        risk = float(inv.get("at_risk") or inv.get("tax_total") or 0)
        reason = inv.get("match_type_label") or inv.get("reason") or "Missing in Government GSTR-2B"
        inv_lines.append(f"  • Inv #{inv_no} dated {inv_dt} | Taxable: ₹{val:,.2f} | At-Risk ITC: ₹{risk:,.2f} ({reason})")

    inv_table_text = "\n".join(inv_lines) if inv_lines else "  • All pending invoices in the current tax period."

    body = (
        f"Dear Accounts Team,\n\n"
        f"Vendor: {vendor_name}\n"
        f"Vendor GSTIN: {vendor_gstin}\n"
        f"Customer: {business.legal_name} (GSTIN: {business.gstin})\n"
        f"Tax Period: {month}\n\n"
        f"During our automated pre-filing reconciliation against the GST Portal (GSTR-2B) for {month}, "
        f"the following invoices issued to us were NOT found or have discrepancies:\n\n"
        f"{inv_table_text}\n\n"
        f"Total Ineligible / At-Risk Credit: ₹{total_at_risk:,.2f}\n\n"
        f"LEGAL NOTICE UNDER CGST ACT, 2017:\n"
        f"Under Section 16(2)(aa) of the CGST Act read with Rule 36(4), our company cannot claim Input Tax Credit (ITC) "
        f"unless these invoices are properly filed by you in your GSTR-1 and reflected in our GSTR-2B. "
        f"Claiming ITC without your filing invites statutory reversal along with 18% p.a. interest.\n\n"
        f"REQUIRED ACTION:\n"
        f"1. Please verify your GSTR-1 filing for {month} immediately.\n"
        f"2. If missing, please upload the invoice(s) in your next return or IFF.\n"
        f"3. Note that per company policy, payment of ₹{total_at_risk:,.2f} may be placed on hold until GSTR-2B confirmation.\n\n"
        f"{f'Note from Accounts: {custom_note}' if custom_note else ''}\n\n"
        f"Regards,\n"
        f"Finance & Compliance Team\n"
        f"{business.legal_name}\n"
        f"GSTIN: {business.gstin}\n"
        f"(Generated via GST CashPilot AI Defaulter Notice System)"
    )
    return subject, body, total_at_risk


@router.post("/{gstin}/notice", response_model=Detail)
def send_vendor_notice(
    gstin: str,
    payload: dict = Body(default={}),
    month: str = Depends(month_param),
    db: Session = Depends(get_db),
    business: Business = Depends(get_business),
):
    v = db.query(Vendor).filter_by(business_id=business.id, gstin=gstin.upper()).first()
    if not v:
        raise HTTPException(404, "Vendor not found")
    
    vd = analytics.vendor_detail(db, business.id, gstin.upper(), month, window=1)
    if not vd:
        raise HTTPException(404, "No vendor data for this period")
    
    invoices = vd.get("invoices") or []
    at_risk_invoices = [inv for inv in invoices if (inv.get("at_risk") or 0) > 0 or inv.get("match_type") in ("missing_in_2b", "amount_mismatch")]
    
    # If no specific invoices are tagged at_risk, use all invoices for this vendor this month
    if not at_risk_invoices:
        at_risk_invoices = invoices

    custom_note = payload.get("custom_note")
    recipient = payload.get("recipient_email") or f"billing@{v.name.lower().replace(' ', '').replace('.', '')[:12]}.in"
    subject, body, total_at_risk = _generate_notice(v.name, v.gstin, business, month, at_risk_invoices, custom_note)

    notice = VendorNotice(
        business_id=business.id,
        vendor_id=v.id,
        month=month,
        recipient_email=recipient,
        subject=subject,
        body=body,
        status="prepared",
        invoice_count=len(at_risk_invoices),
        at_risk_amount=total_at_risk,
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)

    return {
        "success": True,
        "message": f"Notice prepared and saved for {v.name} ({recipient}). No email service is connected, so nothing was delivered.",
        "notice": {
            "id": notice.id,
            "vendor_name": v.name,
            "vendor_gstin": v.gstin,
            "recipient_email": notice.recipient_email,
            "subject": notice.subject,
            "body": notice.body,
            "invoice_count": notice.invoice_count,
            "at_risk_amount": notice.at_risk_amount,
            "sent_at": notice.sent_at.isoformat(),
            "status": notice.status,
        },
    }


@router.post("/send-bulk-notices", response_model=Detail)
def send_bulk_notices(
    payload: dict = Body(default={}),
    month: str = Depends(month_param),
    db: Session = Depends(get_db),
    business: Business = Depends(get_business),
):
    vendors_res = analytics.vendors(db, business.id, month, window=1, sort="at_risk", limit=50)
    items = vendors_res.get("items") or []
    defaulters = [v for v in items if (v.get("at_risk") or 0) > 0]

    sent_notices = []
    total_risk = 0.0

    for def_row in defaulters:
        gstin = def_row["gstin"]
        v = db.query(Vendor).filter_by(business_id=business.id, gstin=gstin).first()
        if not v:
            continue
        vd = analytics.vendor_detail(db, business.id, gstin, month, window=1)
        invoices = (vd.get("invoices") or []) if vd else []
        at_risk_invs = [inv for inv in invoices if (inv.get("at_risk") or 0) > 0 or inv.get("match_type") in ("missing_in_2b", "amount_mismatch")]
        if not at_risk_invs:
            at_risk_invs = invoices

        recipient = f"accounts@{v.name.lower().replace(' ', '').replace('.', '')[:12]}.in"
        subject, body, at_risk_amt = _generate_notice(v.name, v.gstin, business, month, at_risk_invs)
        notice = VendorNotice(
            business_id=business.id,
            vendor_id=v.id,
            month=month,
            recipient_email=recipient,
            subject=subject,
            body=body,
            status="prepared",
            invoice_count=len(at_risk_invs),
            at_risk_amount=at_risk_amt,
        )
        db.add(notice)
        sent_notices.append({
            "vendor_name": v.name,
            "vendor_gstin": v.gstin,
            "recipient_email": recipient,
            "invoice_count": len(at_risk_invs),
            "at_risk_amount": at_risk_amt,
        })
        total_risk += at_risk_amt

    db.commit()

    return {
        "success": True,
        "notices_sent": len(sent_notices),
        "total_at_risk": round(total_risk, 2),
        "vendors": sent_notices,
    }
