from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.controllers.common import month_param
from app.core.database import get_db
from app.core.security import get_business
from app.models import Business, ItcCheck, Match
from app.schemas.views import Detail, ReconList
from app.services import analytics, gemini

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@router.get("", response_model=ReconList)
def items(month: str = Depends(month_param), match_type: Literal["matched", "amount_mismatch", "missing_in_2b", "missing_in_books"] | None = None,
          itc_status: Literal["eligible", "at_risk", "blocked"] | None = None, q: str | None = None, vendor_gstin: str | None = None,
          sort: str = "at_risk", order: Literal["asc", "desc"] = "desc", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
          db: Session = Depends(get_db), business: Business = Depends(get_business)):
    return analytics.reconciliation_items(db, business.id, month, match_type, itc_status, q, vendor_gstin, sort, order, page, page_size)


@router.get("/{match_id}", response_model=Detail)
def detail(match_id: str, db: Session = Depends(get_db), business: Business = Depends(get_business)):
    d = analytics.reconciliation_detail(db, business.id, match_id)
    if not d:
        raise HTTPException(404, "Item not found")
    return d


@router.post("/{match_id}/explain", response_model=Detail)
def explain(match_id: str, db: Session = Depends(get_db), business: Business = Depends(get_business)):
    """Gemini explains the decision in simple words. The decision itself is already made by code; Gemini only writes the words."""
    d = analytics.reconciliation_detail(db, business.id, match_id)
    if not d or not d["decision"]:
        raise HTTPException(404, "No decision to explain")
    if not gemini.enabled():
        raise HTTPException(503, "Gemini is not configured (set GEMINI_API_KEY). The rule-based reason is shown instead.")
    dec = d["decision"]
    prompt = ("Explain this GST input tax credit decision to a small business owner in 3 short sentences of plain English. "
              "Do not change any number or status. Mention what to do next.\n"
              f"Vendor: {d['vendor']['name']}\nMatch result: {d['match']['type']}\nStatus: {dec['status']}\nRule: {dec['rule_label']}\n"
              f"Amounts: eligible {dec['claimable']}, at risk {dec['at_risk']}, blocked {dec['blocked']}\nRule text: "
              + " | ".join(p["body"] for p in d["passages"][:1]))
    try:
        text = gemini.generate_text(prompt)
    except Exception as exc:  # noqa: BLE001
        limited = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
        raise HTTPException(429 if limited else 502, "Gemini's rate limit for this API key was reached. Wait a minute and try again." if limited else f"Gemini could not answer ({type(exc).__name__}). Try again in a moment.") from exc
    chk = db.query(ItcCheck).filter_by(match_id=match_id, business_id=business.id).first()
    chk.llm_explanation = text
    db.commit()
    return {"explanation": text, "engine": "gemini"}
