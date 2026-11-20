from fastapi import APIRouter, Depends, HTTPException

from app.agents.runner import AgentUnavailable, ask_copilot
from app.core.security import CurrentUser, get_business, get_current_user
from app.models import Business
from app.schemas.views import AskBody, Detail

router = APIRouter(prefix="/copilot", tags=["copilot (Google ADK)"])


@router.post("/ask", response_model=Detail)
async def ask(body: AskBody, user: CurrentUser = Depends(get_current_user), business: Business = Depends(get_business)):
    """Asks the Google ADK root agent. The business comes from the token and is passed to the tools through the session state."""
    try:
        return await ask_copilot(body.question, business.id, user.uid, body.month)
    except AgentUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - Gemini or the agent failed: tell the user, do not crash
        text = str(exc) + type(exc).__name__
        if "429" in text or "RESOURCE_EXHAUSTED" in text or "ResourceExhausted" in text:
            raise HTTPException(429, "Gemini's rate limit for this API key was reached. Wait a minute and ask again.") from exc
        if "503" in text or "UNAVAILABLE" in text:
            raise HTTPException(503, "Gemini is busy right now. Try again in a moment.") from exc
        raise HTTPException(502, f"The agents could not answer ({type(exc).__name__}). Try again.") from exc
