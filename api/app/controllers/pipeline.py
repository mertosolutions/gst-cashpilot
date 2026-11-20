from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.controllers.common import month_param
from app.core.database import get_db
from app.core.security import get_business
from app.models import Business, ItcCheck, LegalChunk
from app.schemas.views import PipelineRunOut
from app.services import pipeline, rag
from app.services.util import rules_config

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


@router.get("/rules")
def rules(month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    """The rules the tool applies: the decision rules in the order they run, and the GST passages the RAG layer cites.
    Counts show how often each was used for this business in the selected month."""
    cfg = rules_config()
    checks = db.query(ItcCheck).filter_by(business_id=business.id, month=month).all()
    by_key: dict[str, int] = {}
    cited: dict[str, int] = {}
    for c in checks:
        by_key[c.rule_key] = by_key.get(c.rule_key, 0) + 1
        if c.passage_ids and c.citation:
            cited[c.passage_ids[0]] = cited.get(c.passage_ids[0], 0) + 1
    chunks = db.query(LegalChunk).order_by(LegalChunk.id).all()
    decision = []
    for r in sorted(cfg["decision_rules"], key=lambda x: x["order"]):
        refs = [{"id": c.id, "citation": c.citation} for c in chunks if set(c.tags or []) & set(r["tags"])]
        decision.append({**r, "label": cfg["rule_labels"].get(r["key"], r["key"]), "used": by_key.get(r["key"], 0), "citations": refs[:3]})
    return {"month": month, "engine": rag.backend_name(), "invoices_checked": len(checks), "decision_rules": decision,
            "passages": [{"id": c.id, "citation": c.citation, "topic": c.topic, "body": c.body, "tags": c.tags or [], "used": cited.get(c.id, 0)} for c in chunks],
            "needs_ca_review": True,
            "note": "Passages are simplified paraphrases for the prototype. A CA must verify the exact wording before real use."}
