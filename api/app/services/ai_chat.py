"""Ask CashPilot: every answer is written by Gemini.
For each question the app first collects what Gemini is allowed to use:
  1. DATA: exact results from the saved reconciliation (the same read-only search the result cards use), the month totals, and the top vendors.
  2. RULES: the GST rule passages found by the managed Vertex AI Search (RAG) for the question, with their citations.
Gemini then writes the reply from only those two sources. The result cards still come from the exact search, so numbers never come from the model.
If Gemini is not available the exact local answer is returned and the engine label says so."""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy.orm import Session

from app.services import analytics, gemini, rag, voice_search
from app.services.util import month_label

SYSTEM = """You are CashPilot, a GST assistant for an Indian business. Answer ONLY from the DATA and RULES given in the message.
- Numbers: use the exact figures in DATA. Never calculate new totals, and never invent invoices, vendors, amounts or sections. Write amounts in Indian format with the rupee sign.
- Rules: when you mention a GST rule or section, use only the passages in RULES and cite them, for example "Section 16(2)(aa), CGST Act, 2017".
- RULES may be empty when the question is not about a GST rule: then do not mention any section.
- If DATA and RULES do not contain the answer, say what is missing and what the user can ask instead. Do not guess.
- Be direct: the first sentence answers the question. Then at most 5 short bullet points or two short paragraphs.
- If the question rests on a wrong assumption (for example it calls an at-risk invoice "blocked"), say so politely and explain the real status.
- If the user asks for one or "only one" item, name just one.
- Decision support only. Never say that anything has been filed, paid or sent.
- Reply in the language the user wrote in (the language code is given)."""

_HISTORY_TURNS = 6
log = logging.getLogger("cashpilot.ai")


def _trim(items: list[dict], n: int = 8) -> list[dict]:
    keep = ("vendor", "name", "invoice_no", "match_type", "itc_status", "taxable", "at_risk", "blocked", "claimable", "reason", "citation", "matched_pct", "spend", "gstin")
    return [{k: it[k] for k in keep if k in it} for it in items[:n]]


def _plain(text: str) -> str:
    return re.sub(r"[*_`#>]+", "", text).replace("\n- ", "\n").strip()


def answer(db: Session, business_id: str, text: str, month: str, lang: str = "en-IN", history: list[dict] | None = None) -> dict:
    base = voice_search.answer(db, business_id, text, month, lang)  # exact data for the question (also parses the month)
    month = base["month"]
    code = lang.split("-")[0].lower()
    question = base.get("english") or text
    if not gemini.available():
        base["engine"] = "local intent parser (Gemini is not available right now)"
        return base
    try:
        passages, rag_backend = rag.search_for_chat(db, question)  # managed Vertex AI Search first; the local engine only if it fails
    except Exception:  # noqa: BLE001
        passages, rag_backend = [], "none"
    rules = [{"citation": p["citation"], "topic": p["topic"], "text": p["body"]} for p in passages[:3]]
    m = analytics.month_metrics(db, business_id, month)
    vendors = analytics.vendors(db, business_id, month, window=1, sort="at_risk", limit=5)["items"]
    data = {
        "month": month_label(month), "available_months": [month_label(x) for x in analytics.available_months(db, business_id)],
        "month_totals": {k: m[k] for k in ("invoices", "purchase_taxable", "output_tax", "eligible", "at_risk", "blocked", "cash_safe", "cash_full", "matched",
                                          "amount_mismatch", "missing_in_2b", "missing_in_books", "match_rate")},
        "top_vendors_by_at_risk": [{"name": v["name"], "at_risk": v["at_risk"], "matched_pct": v["matched_pct"]} for v in vendors],
        "search_for_this_question": {"what_the_exact_search_found": base["answer"], "filters": base["filters"], "rows": _trim(base["results"].get("items", []))},
    }
    turns = [f"{h.get('role', 'user')}: {str(h.get('text', ''))[:400]}" for h in (history or [])[-_HISTORY_TURNS:]]
    prompt = (f"Language code: {code}\n\nDATA:\n{json.dumps(data, ensure_ascii=False, default=str)}\n\nRULES:\n{json.dumps(rules, ensure_ascii=False)}\n\n"
              + (f"Conversation so far:\n" + "\n".join(turns) + "\n\n" if turns else "") + f"User question: {text}")
    try:
        reply = gemini.generate_text(prompt, system=SYSTEM)
    except Exception as exc:  # noqa: BLE001
        if gemini.is_quota_error(exc):
            gemini.mark_quota_hit()
        log.warning("chat: Gemini call failed: %s: %s", type(exc).__name__, str(exc)[:160])
        base["engine"] = f"local intent parser (Gemini failed: {type(exc).__name__})"
        return base
    if not reply:
        base["engine"] = "local intent parser (Gemini returned nothing)"
        return base
    used_vertex = rag_backend == "vertex-ai-search"
    base.update(answer=reply, spoken=_plain(reply), spoken_language=code if code != "en" else "en",
                engine=f"Gemini ({gemini.LAST_MODEL['name']}) + " + ("Vertex AI Search (managed RAG)" if used_vertex else "local rule search (managed RAG not reachable)"),
                rag={"backend": rag_backend, "rules": [{"citation": r["citation"], "topic": r["topic"]} for r in rules]})
    return base
