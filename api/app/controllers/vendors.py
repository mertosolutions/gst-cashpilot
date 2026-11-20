from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.controllers.common import month_param
from app.core.database import get_db
from app.core.security import get_business
from app.models import Business
from app.schemas.views import Detail, VendorList
from app.services import analytics

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("", response_model=VendorList)
def list_vendors(month: str = Depends(month_param), window: int = Query(1, ge=1, le=12, description="months to look back, ending at `month`"),
                 sort: str = "at_risk", order: Literal["asc", "desc"] = "desc", limit: int = Query(8, ge=0, le=100), offset: int = Query(0, ge=0),
                 risk: Literal["low", "medium", "high"] | None = None, q: str | None = None,
                 db: Session = Depends(get_db), business: Business = Depends(get_business)):
    return analytics.vendors(db, business.id, month, window, sort, order, limit, risk, q, offset)


@router.get("/{gstin}", response_model=Detail)
def vendor(gstin: str, month: str = Depends(month_param), window: int = Query(6, ge=1, le=12),
           db: Session = Depends(get_db), business: Business = Depends(get_business)):
    d = analytics.vendor_detail(db, business.id, gstin.upper(), month, window)
    if not d:
        raise HTTPException(404, "Vendor not found")
    return d
