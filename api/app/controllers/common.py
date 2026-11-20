from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_business
from app.models import Business
from app.services import analytics


def month_param(month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM; defaults to the latest month with data"),
                db: Session = Depends(get_db), business: Business = Depends(get_business)) -> str:
    if month:
        return month
    months = analytics.available_months(db, business.id)
    if not months:
        raise HTTPException(404, "No data yet. Upload a purchase register and GSTR-2B first.")
    return months[-1]
