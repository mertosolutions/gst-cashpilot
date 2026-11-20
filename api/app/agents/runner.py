"""Runs ADK agents. Requires GEMINI_API_KEY; callers handle AgentUnavailable and fall back."""
from __future__ import annotations

import asyncio
import json
import os

from app.core.config import get_settings

APP_NAME = "gst_cashpilot"


class AgentUnavailable(RuntimeError):
    pass


def _prepare_env() -> None:
    s = get_settings()
    if not s.gemini_enabled:
        raise AgentUnavailable("Gemini is not configured, so the Google ADK agents cannot call it.")
    if s.genai_backend == "vertex":  # ADK then calls Gemini through Vertex AI in your Google Cloud project
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"
        if s.vertex_api_key:
            os.environ["GOOGLE_API_KEY"] = s.vertex_api_key
        else:
            os.environ["GOOGLE_CLOUD_PROJECT"] = s.google_cloud_project or ""
            os.environ["GOOGLE_CLOUD_LOCATION"] = s.google_cloud_location
        return
    os.environ.setdefault("GOOGLE_API_KEY", s.gemini_api_key or "")
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")


async def _run(agent, user_id: str, state: dict, parts: list) -> str:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    svc = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=svc)
    session = await svc.create_session(app_name=APP_NAME, user_id=user_id, state=state)
    final = ""
    async for event in runner.run_async(user_id=user_id, session_id=session.id, new_message=types.Content(role="user", parts=parts)):
        if event.is_final_response() and event.content and event.content.parts:
            final = "".join(p.text or "" for p in event.content.parts if getattr(p, "text", None))
    return final


def _fallback_copilot_answer(question: str, business_id: str, month: str) -> str:
    """Used when the Google ADK agents cannot answer (no Gemini, quota, timeout). It asks the same exact search engine the chat uses,
    so the numbers can never disagree with the rest of the app. A question it does not understand gets an honest scope message."""
    from app.core.database import SessionLocal, set_tenant
    from app.services import voice_search

    with SessionLocal() as db:
        set_tenant(db, business_id)
        res = voice_search.answer(db, business_id, question, month, "en-IN")
        if res["intent"] == "unknown":
            return ("I can answer questions about your **vendors**, **invoices** (at risk, blocked, missing in GSTR-2B or in your books), "
                    "**ITC** and **cash payable**. I could not match that question to your data, so I will not guess. "
                    "Try one of these:\n" + "\n".join(f"- {q}" for q in voice_search.suggestions(db, business_id, month)[:3]))
        return res["answer"]


async def ask_copilot(question: str, business_id: str, user_id: str, month: str) -> dict:
    from app.services import gemini
    try:
        if not gemini.available():  # no key, or Gemini is cooling down after a quota error: answer locally at once
            raise AgentUnavailable("Gemini is not available right now")
        _prepare_env()
        from google.genai import types
        from app.agents.definitions import build_agents
        root, _ = build_agents()
        answer = await asyncio.wait_for(_run(root, user_id, {"business_id": business_id, "month": month}, [types.Part.from_text(text=question)]), timeout=25)
        if answer and len(answer.strip()) > 5:
            q_lower = question.lower()
            agent_role = "Tax Reconciliation Agent" if any(w in q_lower for w in ["cash", "payable", "itc", "match", "credit", "2b"]) else (
                "Vendor Communication Agent" if any(w in q_lower for w in ["vendor", "supplier", "defaulter", "notice", "email", "block"]) else (
                    "GST Legal RAG Agent" if any(w in q_lower for w in ["section", "rule", "act", "law", "penalty", "why", "legal"]) else "Google ADK Multi-Agent"
                )
            )
            return {"answer": answer, "agent": f"{agent_role} (Google ADK)"}
    except Exception as exc:  # noqa: BLE001
        if gemini.is_quota_error(exc):
            gemini.mark_quota_hit()
        # fall back to the local rule-based decision engine

    fallback = _fallback_copilot_answer(question, business_id, month)
    q_lower = question.lower()
    agent_role = "Tax Reconciliation Agent" if any(w in q_lower for w in ["cash", "payable", "itc", "match", "credit", "2b"]) else (
        "Vendor Communication Agent" if any(w in q_lower for w in ["vendor", "supplier", "defaulter", "notice", "email", "block"]) else "GST Legal RAG Agent"
    )
    return {"answer": fallback, "agent": f"{agent_role} (Grounded Fallback)"}


async def extract_with_agent(data: bytes, mime_type: str) -> dict:
    _prepare_env()
    from google.genai import types
    from app.agents.definitions import build_agents
    _, extraction = build_agents()
    text = await _run(extraction, "extractor", {}, [types.Part.from_bytes(data=data, mime_type=mime_type), types.Part.from_text(text="Extract the invoice fields.")])
    return json.loads(text)
