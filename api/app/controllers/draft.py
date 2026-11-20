from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.controllers.common import month_param
from app.core.database import get_db
from app.core.security import get_business
from app.models import Business, Gstr3bDraft
from app.schemas.views import Detail
from app.services import draft_ai, pdf, tax

router = APIRouter(prefix="/draft", tags=["gstr-3b draft"])


import copy
import re
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.controllers.common import month_param
from app.core.database import get_db
from app.core.security import get_business
from app.models import Business, Gstr3bDraft, Gstr3bVersion
from app.schemas.views import Detail
from app.services import draft_ai, pdf, tax

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
    elif active_ver.version_number == 1 and active_ver.created_by.startswith("Pipeline"):
        # the auto-draft follows the data until someone adjusts it: new uploads must not leave v1 showing old numbers
        d = db.query(Gstr3bDraft).filter_by(business_id=business.id, month=month).first()
        if d and d.tables != active_ver.tables:
            active_ver.tables = d.tables
            db.commit()
    
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


def _save_version(db: Session, business: Business, month: str, tables: dict, label: str, summary: str, created_by: str) -> int:
    """Stores `tables` as the next version, makes it the active one and keeps the older versions in the history."""
    existing = db.query(Gstr3bVersion).filter_by(business_id=business.id, month=month).all()
    new_num = max([v.version_number for v in existing] + [0]) + 1
    for v in existing:
        v.is_active = False
    db.add(Gstr3bVersion(business_id=business.id, month=month, version_number=new_num, label=f"v{new_num} ({label})"[:100], change_summary=summary[:300],
                         created_by=created_by[:100], tables=tables, is_active=True))
    d = db.query(Gstr3bDraft).filter_by(business_id=business.id, month=month).first()
    if d:
        d.tables = tables
    else:
        db.add(Gstr3bDraft(business_id=business.id, month=month, tables=tables))
    db.commit()
    return new_num


@router.post("/edit", response_model=Detail)
def edit_draft(payload: dict = Body(...), month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    """Saves a manual edit of the draft tables as a new version (the older versions stay in the history). Derived cash figures are recomputed here."""
    current_tables, _, _ = _get_active_tables_and_versions(db, business, month)
    new_tables, err = draft_ai.sanitize_tables(payload.get("tables") or {}, current_tables)
    if err:
        raise HTTPException(422, err)
    changes = draft_ai.diff_tables(current_tables, new_tables)
    if not changes:
        tables, versions, current_ver = _get_active_tables_and_versions(db, business, month)
        return {"success": False, "message": "No changes to save.", "changes": [], "tables": tables, "versions": versions, "current_version": current_ver}
    note = str(payload.get("note") or "").strip()
    new_num = _save_version(db, business, month, new_tables, "Manual edit", note or "; ".join(changes[:3]), f"{business.legal_name} (manual edit)")
    tables, versions, current_ver = _get_active_tables_and_versions(db, business, month)
    return {"success": True, "message": f"Saved as version v{new_num}", "changes": changes, "tables": tables, "versions": versions, "current_version": current_ver}


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

    # Gemini reads the whole draft document and decides; code validates, applies and recomputes. The keyword rules below are only the fallback.
    ai = draft_ai.ask(db, business.id, month, prompt, current_tables, versions, current_ver)
    if ai:
        answer = ai["answer"]
        created = False
        if ai["action"] == "restore" and ai["restore_version"]:
            target = db.query(Gstr3bVersion).filter_by(business_id=business.id, month=month, version_number=ai["restore_version"]).first()
            if target:
                for v in db.query(Gstr3bVersion).filter_by(business_id=business.id, month=month).all():
                    v.is_active = (v.id == target.id)
                d = db.query(Gstr3bDraft).filter_by(business_id=business.id, month=month).first()
                if d:
                    d.tables = target.tables
                db.commit()
                created = True
            else:
                answer += f"\n\nI could not find version v{ai['restore_version']}."
        elif ai["action"] == "modify" and ai["edited_tables"]:  # a direct edit of the document, for example removing a row
            new_tables, err = draft_ai.sanitize_tables(ai["edited_tables"], current_tables)
            changes = draft_ai.diff_tables(current_tables, new_tables) if not err else []
            if err:
                answer += f"\n\n{err}"
            elif not changes:
                answer += "\n\nThe draft already looks like that, so no new version was created."
            else:
                new_num = _save_version(db, business, month, new_tables, ai["label"] or "Gemini edit", ai["change_summary"] or "; ".join(changes[:3]), "Gemini (GSTR-3B Copilot)")
                answer += f"\n\n**Draft updated to v{new_num}. Changes applied:**\n" + "\n".join(f"- {c}" for c in changes)
                created = True
        elif ai["action"] == "modify":
            new_tables, warns = draft_ai.build_tables(ai["figures"], ai["pct"], ai["itc_adj"], ai["out_adj"])
            new_num = max([v["version_number"] for v in versions] + [current_ver]) + 1
            for v in db.query(Gstr3bVersion).filter_by(business_id=business.id, month=month).all():
                v.is_active = False
            db.add(Gstr3bVersion(business_id=business.id, month=month, version_number=new_num, label=f"v{new_num} ({ai['label'] or 'Gemini adjustment'})"[:100],
                                 change_summary=(ai["change_summary"] or prompt)[:300], created_by="Gemini (GSTR-3B Copilot)", tables=new_tables, is_active=True))
            d = db.query(Gstr3bDraft).filter_by(business_id=business.id, month=month).first()
            if d:
                d.tables = new_tables
            else:
                db.add(Gstr3bDraft(business_id=business.id, month=month, tables=new_tables))
            db.commit()
            sel = next(c for c in new_tables["table_6"]["cases"] if c["key"] == new_tables["summary"]["selected_case"])
            answer += f"\n\n**Draft updated to v{new_num}.** Cash payable in the selected case ({sel['label']}): ₹{sel['total']:,.2f}."
            if warns:
                answer += "\n\n" + "\n".join(f"- {w}" for w in warns)
            created = True
        tables, versions, current_ver = _get_active_tables_and_versions(db, business, month)
        return {"answer": answer, "version_created": created, "current_version": current_ver, "versions": versions, "tables": tables, "engine": ai["engine"]}
    fallback_engine = f"keyword rules (Gemini was not used: {draft_ai.LAST_ERROR['why'] or 'unavailable'})"
    # Without Gemini only the short fixed commands (the buttons) are understood. Anything else is refused instead of being guessed at, so no wrong version is created.
    if len(p_lower) > 70 or re.search(r"\d", p_lower):
        tables, versions, current_ver = _get_active_tables_and_versions(db, business, month)
        return {"answer": ("I could not use Gemini for this request just now, so **I changed nothing**. Without Gemini I only understand the short buttons above "
                           "(conservative, aggressive, explain). You can edit any value or remove a row yourself with the **pencil icon** on the draft, or ask again in a minute."),
                "version_created": False, "current_version": current_ver, "versions": versions, "tables": tables, "engine": fallback_engine}

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
            "engine": fallback_engine,
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
            "engine": fallback_engine,
        }

    # Case 3: Explanation questions
    else:
        t4 = current_tables.get("table_4", {})
        t3 = current_tables.get("table_3_1", {})
        t6 = current_tables.get("table_6", {})
        cases = t6.get("cases", [])
        cash_a = sum(cases[0]["cash"].values()) if cases else 0
        cash_b = sum(cases[1]["cash"].values()) if len(cases) > 1 else 0

        rows = t4.get("rows", [])
        def row_total(match) -> float:  # rows are found by label: custom versions add rows, so positions are not fixed
            r = next((x for x in rows if match(x["label"].lower())), None)
            return round(sum((r.get("tax") or {}).values()), 2) if r else 0.0
        taxable = t3.get("taxable_value", 0) or 0
        output_tax = round(sum((t3.get("tax") or {}).values()), 2)
        eligible = row_total(lambda s: s.startswith("(a)"))
        at_risk = row_total(lambda s: s.startswith("at risk - not"))
        blocked = row_total(lambda s: "blocked" in s)
        explanation = (
            f"### GSTR-3B Draft Analysis for {month} (Version v{current_ver})\n\n"
            f"• **Table 3.1 (Outward Supplies):** Total taxable value ₹{taxable:,.2f} with output tax liability ₹{output_tax:,.2f}.\n"
            f"• **Table 4 (ITC):** Credit confirmed by GSTR-2B is ₹{eligible:,.2f}. At risk (not confirmed) is ₹{at_risk:,.2f}. Blocked under Section 17(5) is ₹{blocked:,.2f}.\n"
            f"• **Table 6 (Payment of Tax):**\n"
            f"  - **Case A (Safe):** Pay **₹{cash_a:,.2f}** in cash by claiming only 2B confirmed credit.\n"
            f"  - **Case B (Working Capital):** Pay **₹{cash_b:,.2f}** in cash if you also claim the at-risk credit.\n\n"
            f"💡 *Tip:* Ask me: `\"Switch to conservative mode\"` or `\"Create a new draft claiming all credit\"` to automatically create a new version."
        )
        return {
            "answer": explanation,
            "version_created": False,
            "current_version": current_ver,
            "versions": versions,
            "tables": current_tables,
            "engine": fallback_engine,
        }


@router.get("/pdf")
def draft_pdf(month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    tables, _, _ = _get_active_tables_and_versions(db, business, month)
    if not tables:
        raise HTTPException(404, "No draft")
    data = pdf.draft_pdf(business.legal_name, business.gstin, month, tables)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="gstr3b-draft-{month}.pdf"'})
