from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.controllers.common import month_param
from app.core.database import get_db
from app.core.security import get_business
from app.models import Business
from app.schemas.views import DashboardSummary, Insight, MonthMetrics
from app.services import analytics

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def summary(month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    return analytics.dashboard_summary(db, business.id, month)


@router.get("/trends", response_model=list[MonthMetrics])
def trends(month: str = Depends(month_param), months: int = Query(6, ge=2, le=24), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    return analytics.trends(db, business.id, month, months)


@router.get("/insights", response_model=list[Insight])
def insights(month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    return analytics.insights(db, business.id, month)
