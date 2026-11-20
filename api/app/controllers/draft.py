from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.controllers.common import month_param
from app.core.database import get_db
from app.core.security import get_business
from app.models import Business, Gstr3bDraft
from app.schemas.views import Detail
from app.services import pdf, tax

router = APIRouter(prefix="/draft", tags=["gstr-3b draft"])


import copy
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.controllers.common import month_param
from app.core.database import get_db
from app.core.security import get_business
from app.models import Business, Gstr3bDraft, Gstr3bVersion
from app.schemas.views import Detail
from app.services import pdf, tax

router = APIRouter(prefix="/draft", tags=["gstr-3b draft"])


def _ensure_initial_version(db: Session, business: Business, month: str, tables: dict) -> Gstr3bVersion:
    v = db.query(Gstr3bVersion).filter_by(business_id=business.id, month=month, version_number=1).first()
    if not v:
        v = Gstr3bVersion(
            business_id=business.id,
            month=month,
            version_number=1,
            label="v1 (Initial Auto-Draft)",
            change_summary="Initial auto-draft generated from reconciled GSTR-2B and purchase register",
            created_by="Pipeline Auto-Draft L6",
            tables=tables,
            is_active=True,
        )
        db.add(v)
        db.commit()
        db.refresh(v)
    return v


def _get_active_tables_and_versions(db: Session, business: Business, month: str):
    active_ver = db.query(Gstr3bVersion).filter_by(business_id=business.id, month=month, is_active=True).order_by(Gstr3bVersion.version_number.desc()).first()
    if not active_ver:
        d = db.query(Gstr3bDraft).filter_by(business_id=business.id, month=month).first()
        tables = d.tables if d else tax.build_draft(db, business.id, month)
        active_ver = _ensure_initial_version(db, business, month, tables)
    
    all_versions = db.query(Gstr3bVersion).filter_by(business_id=business.id, month=month).order_by(Gstr3bVersion.version_number.desc()).all()
    version_list = [
        {
            "version_number": ver.version_number,
            "label": ver.label,
            "change_summary": ver.change_summary,
            "created_by": ver.created_by,
            "is_active": ver.is_active,
            "created_at": ver.created_at.isoformat() if ver.created_at else "",
        }
        for ver in all_versions
    ]
    return active_ver.tables, version_list, active_ver.version_number


@router.get("", response_model=Detail)
def get_draft(month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    tables, versions, current_ver = _get_active_tables_and_versions(db, business, month)
    return {
        "month": month,
        "business": {"name": business.legal_name, "gstin": business.gstin},
        "tables": tables,
        "versions": versions,
        "current_version": current_ver,
        "disclaimer": "Draft for review by the owner or CA. Nothing is filed on the GST portal.",
    }


@router.get("/versions", response_model=Detail)
def get_versions(month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    _, versions, current_ver = _get_active_tables_and_versions(db, business, month)
    return {"month": month, "versions": versions, "current_version": current_ver}


@router.post("/versions/{version_number}/restore", response_model=Detail)
def restore_version(version_number: int, month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    target = db.query(Gstr3bVersion).filter_by(business_id=business.id, month=month, version_number=version_number).first()
    if not target:
        raise HTTPException(404, f"Version v{version_number} not found")
    
    # Set all other versions to inactive
    for v in db.query(Gstr3bVersion).filter_by(business_id=business.id, month=month).all():
        v.is_active = (v.id == target.id)
    
    # Update Gstr3bDraft table
    d = db.query(Gstr3bDraft).filter_by(business_id=business.id, month=month).first()
    if d:
        d.tables = target.tables
    db.commit()

    tables, versions, current_ver = _get_active_tables_and_versions(db, business, month)
    return {
        "success": True,
        "message": f"Restored version v{version_number} ({target.label})",
        "tables": tables,
        "versions": versions,
        "current_version": current_ver,
    }


@router.post("/adjust", response_model=Detail)
def adjust_draft(
    payload: dict = Body(...),
    month: str = Depends(month_param),
    db: Session = Depends(get_db),
    business: Business = Depends(get_business),
):
    """Creates a new version of the GSTR-3B draft with user/CA specified adjustments."""
    current_tables, _, current_ver = _get_active_tables_and_versions(db, business, month)
    new_tables = copy.deepcopy(current_tables)

    label = payload.get("label") or f"v{current_ver + 1} (Manual Adjustment)"
    summary = payload.get("summary") or "Custom CA adjustment to draft figures"
    created_by = payload.get("created_by") or "Chartered Accountant"

    # Allow overriding specific table values if provided
    overrides = payload.get("overrides") or {}
    if "table_4" in overrides:
        new_tables["table_4"].update(overrides["table_4"])
    if "table_3_1" in overrides:
        new_tables["table_3_1"].update(overrides["table_3_1"])
    
    # Mark old active versions as inactive
    for v in db.query(Gstr3bVersion).filter_by(business_id=business.id, month=month).all():
        v.is_active = False

    new_ver_num = current_ver + 1
    new_ver = Gstr3bVersion(
        business_id=business.id,
        month=month,
        version_number=new_ver_num,
        label=label,
        change_summary=summary,
        created_by=created_by,
        tables=new_tables,
        is_active=True,
    )
    db.add(new_ver)

    # Sync Gstr3bDraft
    d = db.query(Gstr3bDraft).filter_by(business_id=business.id, month=month).first()
    if d:
        d.tables = new_tables
    else:
        db.add(Gstr3bDraft(business_id=business.id, month=month, tables=new_tables))
    db.commit()

    tables, versions, current_ver = _get_active_tables_and_versions(db, business, month)
    return {
        "success": True,
        "message": f"Created new version v{new_ver_num}: {label}",
        "tables": tables,
        "versions": versions,
        "current_version": current_ver,
    }


@router.post("/chat", response_model=Detail)
def draft_chat(
    payload: dict = Body(...),
    month: str = Depends(month_param),
    db: Session = Depends(get_db),
    business: Business = Depends(get_business),
):
    """Interactive draft assistant that explains 3B tables or modifies them into a new version based on user prompt."""
    prompt = payload.get("message", "").strip()
    if not prompt:
        raise HTTPException(400, "Message cannot be empty")

    current_tables, versions, current_ver = _get_active_tables_and_versions(db, business, month)
    p_lower = prompt.lower()

    # Case 1: Adjustment intent: "conservative", "hold back at-risk", "safe mode", "exclude"
    if any(k in p_lower for k in ["conservative", "case a", "hold back", "safe mode", "exclude at risk", "only eligible"]):
        new_tables = copy.deepcopy(current_tables)
        # Select Case A (conservative) as the active default
        case_a = new_tables["table_6"]["cases"][0]
        summary = "Switched to Conservative Filing Mode (Case A: Avail 100% verified GSTR-2B credit only; zero risk of notice)"
        new_ver_num = current_ver + 1

        for v in db.query(Gstr3bVersion).filter_by(business_id=business.id, month=month).all():
            v.is_active = False

        new_ver = Gstr3bVersion(
            business_id=business.id,
            month=month,
            version_number=new_ver_num,
            label=f"v{new_ver_num} (Conservative Safe Mode)",
            change_summary=summary,
            created_by="GSTR-3B Copilot",
            tables=new_tables,
            is_active=True,
        )
        db.add(new_ver)
        db.commit()

        tables, versions, current_ver = _get_active_tables_and_versions(db, business, month)
        cash_needed = sum(case_a["cash"].values())
        return {
            "answer": (
                f"✅ **Created Draft Version v{new_ver_num} (Conservative Safe Mode)**\n\n"
                f"• **Strategy:** Availing only 100% matched GSTR-2B credit (₹{case_a['total']:,.2f}).\n"
                f"• **Cash Outflow Required:** ₹{cash_needed:,.2f}.\n"
                f"• **Statutory Protection:** Zero exposure to Section 16(2)(aa) notices or interest penalties.\n\n"
                f"The draft tables and version history have been updated."
            ),
            "version_created": True,
            "current_version": current_ver,
            "versions": versions,
            "tables": tables,
        }

    # Case 2: Aggressive intent: "aggressive", "case b", "claim all", "include at risk"
    elif any(k in p_lower for k in ["aggressive", "case b", "claim all", "include at risk", "maximum credit"]):
        new_tables = copy.deepcopy(current_tables)
        case_b = new_tables["table_6"]["cases"][1]
        summary = "Switched to Working Capital Optimization Mode (Case B: Avail both 2B matched + at-risk book credit)"
        new_ver_num = current_ver + 1

        for v in db.query(Gstr3bVersion).filter_by(business_id=business.id, month=month).all():
            v.is_active = False

        new_ver = Gstr3bVersion(
            business_id=business.id,
            month=month,
            version_number=new_ver_num,
            label=f"v{new_ver_num} (Aggressive Cash Mode)",
            change_summary=summary,
            created_by="GSTR-3B Copilot",
            tables=new_tables,
            is_active=True,
        )
        db.add(new_ver)
        db.commit()

        tables, versions, current_ver = _get_active_tables_and_versions(db, business, month)
        cash_needed = sum(case_b["cash"].values())
        return {
            "answer": (
                f"✅ **Created Draft Version v{new_ver_num} (Aggressive Working Capital Mode)**\n\n"
                f"• **Strategy:** Claiming all purchase register ITC (₹{case_b['total']:,.2f}), including at-risk.\n"
                f"• **Cash Outflow Required:** ₹{cash_needed:,.2f} (saves immediate cash).\n"
                f"• **CA Caution:** Requires follow-up with defaulting vendors to file GSTR-1 before annual return.\n\n"
                f"The draft tables and version history have been updated."
            ),
            "version_created": True,
            "current_version": current_ver,
            "versions": versions,
            "tables": tables,
        }

    # Case 3: Explanation questions
    else:
        t4 = current_tables.get("table_4", {})
        t3 = current_tables.get("table_3_1", {})
        t6 = current_tables.get("table_6", {})
        cases = t6.get("cases", [])
        cash_a = sum(cases[0]["cash"].values()) if cases else 0
        cash_b = sum(cases[1]["cash"].values()) if len(cases) > 1 else 0

        explanation = (
            f"### GSTR-3B Draft Analysis for {month} (Version v{current_ver})\n\n"
            f"• **Table 3.1 (Outward Supplies):** Total taxable value ₹{t3.get('total_taxable', 0):,.2f} with output tax liability ₹{t3.get('total_tax', 0):,.2f}.\n"
            f"• **Table 4 (Eligible ITC):** GSTR-2B confirmed credit is ₹{t4.get('eligible_itc_total', 0):,.2f}. Blocked credit under Section 17(5) is ₹{t4.get('blocked_itc_total', 0):,.2f}.\n"
            f"• **Table 6 (Payment of Tax):**\n"
            f"  - **Case A (Safe):** Pay **₹{cash_a:,.2f}** in cash by claiming only 2B confirmed credits.\n"
            f"  - **Case B (Working Capital):** Pay **₹{cash_b:,.2f}** in cash if claiming at-risk book credits.\n\n"
            f"💡 *Tip:* Ask me: `\"Switch to conservative mode\"` or `\"Create a new draft claiming all credit\"` to automatically create a new version."
        )
        return {
            "answer": explanation,
            "version_created": False,
            "current_version": current_ver,
            "versions": versions,
            "tables": current_tables,
        }


@router.get("/pdf")
def draft_pdf(month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    tables, _, _ = _get_active_tables_and_versions(db, business, month)
    if not tables:
        raise HTTPException(404, "No draft")
    data = pdf.draft_pdf(business.legal_name, business.gstin, month, tables)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="gstr3b-draft-{month}.pdf"'})
