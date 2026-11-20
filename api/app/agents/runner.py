"""Runs ADK agents. Requires GEMINI_API_KEY; callers handle AgentUnavailable and fall back."""
from __future__ import annotations

import json
import os

from app.core.config import get_settings

APP_NAME = "gst_cashpilot"


class AgentUnavailable(RuntimeError):
    pass


def _prepare_env() -> None:
    s = get_settings()
    if not s.gemini_api_key:
        raise AgentUnavailable("GEMINI_API_KEY is not set, so the Google ADK agents cannot call Gemini.")
    os.environ.setdefault("GOOGLE_API_KEY", s.gemini_api_key)
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
    from app.core.database import SessionLocal, set_tenant
    from app.models import ItcCheck, PurchaseInvoice
    from app.services import analytics, tax

    q = question.lower()
    with SessionLocal() as db:
        set_tenant(db, business_id)

        # 1. Vendors blocking credit
        if any(w in q for w in ("vendor", "block", "who", "credit")):
            v = analytics.vendors(db, business_id, month, window=1, sort="at_risk", limit=5)
            items = v.get("items", [])
            if not items:
                return f"No vendors are currently blocking credit in {month}."
            lines = [f"Vendors blocking the most credit in {month}:"]
            for i, item in enumerate(items, 1):
                lines.append(f"{i}. **{item['name']}** ({item['gstin']}): ₹{item['at_risk']:,.2f} at risk across {item['invoices']} invoice(s) — {item['matched_pct']}% matched ({item['risk_level']} risk)")
            lines.append(f"\nTotal at-risk credit from top vendors: **₹{v.get('total_at_risk', 0):,.2f}** (Top 3 account for {v.get('top3_share', 0)}% of all blocked credit).")
            lines.append("\n*Recommendation*: Request these vendors to file their GSTR-1 before the 11th of the month to release this credit.")
            return "\n".join(lines)

        # 2. Cash payable in both cases
        if any(w in q for w in ("cash", "payable", "case", "how much", "pay")):
            cp = tax.calculate_cash_payable(db, business_id, month)
            safe = cp.get("cash_safe", 0)
            risk = cp.get("cash_with_risk", 0)
            diff = safe - risk
            return (
                f"**Cash Payable Summary for {month}:**\n\n"
                f"• **Case A (Safe Strategy — Claiming only Eligible ITC):**\n"
                f"  Cash Payable is **₹{safe:,.2f}** in GSTR-3B Table 6. Eliminates department notice liability.\n\n"
                f"• **Case B (Aggressive Strategy — Claiming Eligible + At-Risk ITC):**\n"
                f"  Cash Payable is **₹{risk:,.2f}**, saving **₹{diff:,.2f}** in immediate cash outflow.\n\n"
                f"⚠️ *Note*: If vendors do not file by the deadline, claiming the ₹{diff:,.2f} in Case B may attract a notice under Section 73 with 18% p.a. interest."
            )

        # 3. Largest at-risk invoice
        if any(w in q for w in ("largest", "risk", "why")):
            chk = (
                db.query(ItcCheck)
                .join(PurchaseInvoice, ItcCheck.purchase_invoice_id == PurchaseInvoice.id)
                .filter(ItcCheck.business_id == business_id, PurchaseInvoice.month == month, ItcCheck.status == "at_risk")
                .order_by(ItcCheck.at_risk_total.desc())
                .first()
            )
            if chk:
                inv = chk.invoice
                return (
                    f"The largest at-risk invoice in {month} is **{inv.invoice_no}** from **{inv.vendor.name}** "
                    f"for **₹{chk.at_risk_total:,.2f}**.\n\n"
                    f"• **Reason:** {chk.reason}\n"
                    f"• **Cited Rule:** {chk.citation or 'Section 16(2)(aa) of CGST Act'}\n"
                    f"• **Action required:** Follow up with {inv.vendor.name} to upload invoice {inv.invoice_no} in GSTR-1."
                )

        # 4. General month summary fallback
        summ = analytics.summary(db, business_id, month)
        kpi_map = {k["key"]: k["value"] for k in summ.get("kpis", [])}
        return (
            f"**GST Summary for {month}:**\n"
            f"• Total Purchase Spend: ₹{kpi_map.get('purchase_total', 0):,.2f}\n"
            f"• Eligible ITC: ₹{kpi_map.get('eligible', 0):,.2f}\n"
            f"• At-Risk ITC: ₹{kpi_map.get('at_risk', 0):,.2f}\n"
            f"• Safe Cash Payable: ₹{kpi_map.get('cash_safe', 0):,.2f}\n"
            f"• Matched Invoices: {kpi_map.get('matched', 0)} ({kpi_map.get('match_pct', 0)}% match rate)."
        )


async def ask_copilot(question: str, business_id: str, user_id: str, month: str) -> dict:
    from app.services import gemini
    try:
        if not gemini.available():  # no key, or Gemini is cooling down after a quota error: answer locally at once
            raise AgentUnavailable("Gemini is not available right now")
        _prepare_env()
        from google.genai import types
        from app.agents.definitions import build_agents
        root, _ = build_agents()
        answer = await _run(root, user_id, {"business_id": business_id, "month": month}, [types.Part.from_text(text=question)])
        if answer and len(answer.strip()) > 5:
            return {"answer": answer, "agent": "cashpilot_root_agent (Google ADK)"}
    except Exception as exc:  # noqa: BLE001
        if gemini.is_quota_error(exc):
            gemini.mark_quota_hit()
        # fall back to the local rule-based decision engine

    fallback = _fallback_copilot_answer(question, business_id, month)
    return {"answer": fallback, "agent": "cashpilot_decision_engine (Grounded Fallback)"}


async def extract_with_agent(data: bytes, mime_type: str) -> dict:
    _prepare_env()
    from google.genai import types
    from app.agents.definitions import build_agents
    _, extraction = build_agents()
    text = await _run(extraction, "extractor", {}, [types.Part.from_bytes(data=data, mime_type=mime_type), types.Part.from_text(text="Extract the invoice fields.")])
    return json.loads(text)
