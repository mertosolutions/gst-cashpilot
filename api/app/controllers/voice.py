from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.controllers.common import month_param
from app.core.database import get_db
from app.core.security import get_business
from app.models import Business
from app.schemas.views import Detail
from app.services import ai_chat, voice_search

router = APIRouter(prefix="/voice", tags=["voice search"])


class VoiceQuery(BaseModel):
    text: str = Field(min_length=2, max_length=400, description="What the browser heard (speech to text) or what the user typed")
    lang: str = "en-IN"
    month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    history: list[dict] = Field(default_factory=list, max_length=12, description="Earlier turns of this conversation: [{role, text}]")


@router.post("/query", response_model=Detail)
def query(body: VoiceQuery, month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    """Answers a spoken or typed question. Gemini writes the reply from the saved results and the rule passages found by the managed RAG. Read-only."""
    return ai_chat.answer(db, business.id, body.text, body.month or month, body.lang, body.history)


@router.get("/suggestions", response_model=list[str])
def suggestions(month: str = Depends(month_param), db: Session = Depends(get_db), business: Business = Depends(get_business)):
    """Example questions built from this business's own data."""
    return voice_search.suggestions(db, business.id, month)
