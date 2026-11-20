from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.controllers.common import month_param
from app.core.database import get_db
from app.core.security import get_business
from app.models import Business, Gstr3bDraft
from app.schemas.views import Detail
from app.services import pdf, tax

router = APIRouter(prefix="/draft", tags=["gstr-3b draft"])


def _tables(db, business, month):
    d = db.query(Gstr3bDraft).filter_by(business_id=business.id, month=month).first()
    return d.tables if d else tax.build_draft(db, business.id, month)


@router.get("", response_model=Detail)
def get_draft(month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    return {"month": month, "business": {"name": business.legal_name, "gstin": business.gstin}, "tables": _tables(db, business, month),
            "disclaimer": "Draft for review by the owner or CA. Nothing is filed on the GST portal."}


@router.get("/pdf")
def draft_pdf(month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    tables = _tables(db, business, month)
    if not tables:
        raise HTTPException(404, "No draft")
    data = pdf.draft_pdf(business.legal_name, business.gstin, month, tables)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="gstr3b-draft-{month}.pdf"'})
