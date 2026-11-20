from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import dialect_name, get_db
from app.core.security import CurrentUser, get_business, get_current_user
from app.models import Business, LegalChunk
from app.schemas.views import Me, SystemStatus
from app.services import analytics, pipeline, rag
from app.services.util import month_label

router = APIRouter(tags=["system"])


@router.get("/me", response_model=Me)
def me(user: CurrentUser = Depends(get_current_user), business: Business = Depends(get_business)):
    return Me(uid=user.uid, business_id=business.id, legal_name=business.legal_name, gstin=business.gstin, auth_mode=get_settings().auth_mode)


@router.get("/system/status", response_model=SystemStatus)
def status(db: Session = Depends(get_db)):
    s = get_settings()
    try:
        import google.adk as adk
        adk_version = getattr(adk, "__version__", "installed")
    except Exception:  # noqa: BLE001
        adk_version = "not installed"
    return SystemStatus(
        api="ok", database=f"{dialect_name()} ({'AlloyDB-ready' if dialect_name() == 'postgresql' else 'local'})", auth_mode=s.auth_mode,
        gemini_configured=s.gemini_enabled, gemini_model=s.gemini_model, embedding_engine=rag.current_engine(), adk_version=adk_version,
        rules_indexed=db.query(func.count(LegalChunk.id)).scalar() or 0,
        tenant_isolation="row level security + token scoped queries" if dialect_name() == "postgresql" else "token scoped queries (RLS applies on AlloyDB)")


@router.get("/months")
def months(db: Session = Depends(get_db), business: Business = Depends(get_business)):
    ms = analytics.available_months(db, business.id)
    return {"months": [{"month": m, "label": month_label(m)} for m in ms], "latest": ms[-1] if ms else None}


@router.get("/layers")
def layers():
    return pipeline.layer_catalog()
