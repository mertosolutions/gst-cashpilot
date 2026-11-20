from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.controllers.common import month_param
from app.core.database import get_db
from app.core.security import get_business
from app.models import Business
from app.schemas.views import PipelineRunOut
from app.services import pipeline

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _out(run) -> PipelineRunOut:
    return PipelineRunOut(id=run.id, month=run.month, status=run.status, total_ms=run.total_ms, started_at=run.started_at.isoformat(),
                          finished_at=run.finished_at.isoformat() if run.finished_at else None, stages=run.stages)


@router.post("/run", response_model=PipelineRunOut)
def run(month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    return _out(pipeline.run_pipeline(db, business.id, month))


@router.get("/latest", response_model=PipelineRunOut)
def latest(month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    r = pipeline.latest_run(db, business.id, month)
    if not r:
        raise HTTPException(404, "The processing layers have not run for this month yet")
    return _out(r)
