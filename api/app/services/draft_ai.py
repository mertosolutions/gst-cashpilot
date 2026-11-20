"""GSTR-3B draft assistant driven by Gemini.
Gemini is given the whole draft document (Tables 3.1, 4 and 6 of the active version), the month's reconciled figures, the rule passages found by the
managed RAG for the request, and the version history. It answers with JSON: either an explanation, or a set of adjustments to apply.
Plain code validates the adjustments, rebuilds the tables and recomputes the cash payable, so arithmetic never comes from the model.
The result is saved as a new version and shown in the draft."""
from __future__ import annotations

import copy
import json
import logging

from sqlalchemy.orm import Session

from app.services import gemini, rag, tax

HEADS = ("igst", "cgst", "sgst")
log = logging.getLogger("cashpilot.ai")
LAST_ERROR = {"why": ""}  # why the last request could not use Gemini, shown next to the keyword fallback answer

SYSTEM = """You are the GSTR-3B drafting assistant of an Indian business. You receive the CURRENT DRAFT document (Table 3.1 outward supplies, Table 4 input tax credit,
Table 6 payment of tax, and the adjustments already applied), the month's FIGURES, GST RULES found for the request, and the VERSION HISTORY.
Decide what the user wants and answer with ONLY a JSON object:
{
 "action": "explain" | "modify" | "restore",
 "answer": "markdown reply to the user: what you did or the explanation. Cite a rule only if it appears in RULES.",
 "label": "short version label, for example 'Claim 50% of at-risk credit' (modify only)",
 "change_summary": "one sentence saying what changed and why (modify only)",
 "claim_at_risk_percent": number from 0 to 100 = the share of the at-risk ITC (credit not confirmed in GSTR-2B) to claim in the selected case (modify only),
 "itc_adjustments": [{"head": "igst"|"cgst"|"sgst", "amount": number (positive adds claimed ITC, negative reduces it), "reason": "text"}],
 "output_adjustments": [{"head": "igst"|"cgst"|"sgst", "amount": number (positive adds output tax, negative reduces it), "reason": "text"}],
 "restore_version": number (restore only)
}
Rules for you:
- Adjustments are measured from the ORIGINAL auto-draft figures in FIGURES, not from the current draft. The CURRENT DRAFT shows the adjustments already applied under summary.adjustments;
  repeat the ones the user wants to keep and add or change the new ones.
- claim_at_risk_percent already claims that share of the at-risk credit. Do NOT also add itc_adjustments for the same amounts: itc_adjustments are only for extra manual changes the user asks for
  (for example "reduce CGST credit by 3000"). Without such a request, itc_adjustments must be empty.
- Blocked credit (Section 17(5)) can never be claimed. Do not add ITC above eligible plus at-risk. Say so if the user asks for it.
- Use "explain" when the user only asks a question. Use "modify" only when the user clearly asks for a change. When a request is unclear, use "explain" and ask what they mean.
- Never invent figures. Do not do arithmetic for totals: the app recomputes them. Do not claim anything is filed. This is a draft for the owner or a CA to review."""


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _clean(adjs, cap_abs: float = 1e9) -> list[dict]:
    out = []
    for a in adjs if isinstance(adjs, list) else []:
        head = str((a or {}).get("head", "")).lower()
        amt = max(-cap_abs, min(cap_abs, _num((a or {}).get("amount"))))
        if head in HEADS and amt:
            out.append({"head": head, "amount": round(amt, 2), "reason": str((a or {}).get("reason", ""))[:200]})
    return out


def build_tables(f: dict, pct: float, itc_adj: list[dict], out_adj: list[dict]) -> tuple[dict, list[str]]:
    """Rebuilds the draft from the month's figures plus the adjustments. Returns the tables and warnings about anything that was limited."""
    warnings: list[str] = []
    pct = max(0.0, min(100.0, pct))
    out = {h: f["output"][h] for h in HEADS}
    for a in out_adj:
        out[a["head"]] = max(0.0, round(out[a["head"]] + a["amount"], 2))
    claim = {h: f["eligible"][h] + f["at_risk"][h] * pct / 100.0 for h in HEADS}
    for a in itc_adj:
        claim[a["head"]] += a["amount"]
    for h in HEADS:
        ceiling = f["eligible"][h] + f["at_risk"][h]
        if claim[h] > ceiling + 0.005:
            warnings.append(f"{h.upper()} credit was limited to {ceiling:,.2f}: you cannot claim more than the eligible plus at-risk credit.")
            claim[h] = ceiling
        claim[h] = round(max(0.0, claim[h]), 2)
    cash = lambda itc: {h: round(max(0.0, out[h] - itc[h]), 2) for h in HEADS}  # noqa: E731
    eligible = {h: f["eligible"][h] for h in HEADS}
    both = {h: round(f["eligible"][h] + f["at_risk"][h], 2) for h in HEADS}
    cases = [
        {"key": "A", "label": "Case A: claim only Eligible ITC", "itc_claimed": eligible, "cash": cash(eligible), "total": round(sum(cash(eligible).values()), 2)},
        {"key": "B", "label": "Case B: claim Eligible + At risk ITC", "itc_claimed": both, "cash": cash(both), "total": round(sum(cash(both).values()), 2)},
    ]
    custom = bool(itc_adj) or (0 < pct < 100)
    selected = "C" if custom else ("B" if pct >= 100 else "A")
    if custom:
        cases.append({"key": "C", "label": f"Case C: custom ({pct:g}% of at-risk claimed" + (", with adjustments)" if itc_adj else ")"),
                      "itc_claimed": claim, "cash": cash(claim), "total": round(sum(cash(claim).values()), 2)})
    held = {h: round(f["at_risk"][h] * (1 - pct / 100.0), 2) for h in HEADS}
    rows = [{"label": "(A) ITC available - confirmed in GSTR-2B", "tax": eligible},
            {"label": "At risk - not confirmed (hold back)", "tax": {h: f["at_risk"][h] for h in HEADS}}]
    if custom:
        rows.append({"label": f"At risk claimed in the selected case ({pct:g}%)", "tax": {h: round(f["at_risk"][h] * pct / 100.0, 2) for h in HEADS}})
        rows.append({"label": "At risk held back in the selected case", "tax": held})
    if itc_adj:
        rows.append({"label": "Manual ITC adjustment", "tax": {h: round(sum(a["amount"] for a in itc_adj if a["head"] == h), 2) for h in HEADS}})
    rows.append({"label": "(D) Ineligible ITC - blocked", "tax": {h: f["blocked"][h] for h in HEADS}})
    tables = {
        "table_3_1": {"title": "3.1 Outward supplies (tax on sales)", "taxable_value": f["sales_taxable"], "tax": out},
        "table_4": {"title": "4 Eligible ITC", "rows": rows},
        "table_6": {"title": "6 Payment of tax", "cases": cases},
        "summary": {"cash_saved_by_case_b": round(cases[0]["total"] - cases[1]["total"], 2), "has_sales": f["has_sales"], "selected_case": selected,
                    "adjustments": {"claim_at_risk_percent": pct, "itc_adjustments": itc_adj, "output_adjustments": out_adj}},
    }
    return tables, warnings


def ask(db: Session, business_id: str, month: str, message: str, current_tables: dict, versions: list[dict], current_ver: int) -> dict | None:
    """Returns Gemini's decision (already validated) or None when Gemini cannot be used."""
    LAST_ERROR["why"] = ""
    if not gemini.available():
        LAST_ERROR["why"] = "Gemini is not available right now"
        return None
    try:
        passages, rag_backend = rag.search_for_chat(db, message)
    except Exception:  # noqa: BLE001
        passages, rag_backend = [], "none"
    f = tax.figures(db, business_id, month)
    prompt = (f"CURRENT DRAFT (version v{current_ver}):\n{json.dumps(current_tables, ensure_ascii=False, default=str)}\n\n"
              f"FIGURES (original auto-draft, per head):\n{json.dumps({k: f[k] for k in ('sales_taxable', 'output', 'eligible', 'at_risk', 'blocked', 'cash_a', 'cash_b')}, default=str)}\n\n"
              f"RULES:\n{json.dumps([{'citation': p['citation'], 'topic': p['topic'], 'text': p['body']} for p in passages[:3]], ensure_ascii=False)}\n\n"
              f"VERSION HISTORY:\n{json.dumps([{k: v[k] for k in ('version_number', 'label', 'change_summary', 'is_active')} for v in versions], default=str)}\n\n"
              f"USER REQUEST: {message}")
    try:
        d = gemini.generate_json(prompt, system=SYSTEM)
    except Exception as exc:  # noqa: BLE001
        if gemini.is_quota_error(exc):
            gemini.mark_quota_hit()
        LAST_ERROR["why"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        log.warning("draft assistant: Gemini call failed: %s", LAST_ERROR["why"])
        return None
    if not isinstance(d, dict) or not d.get("answer"):
        LAST_ERROR["why"] = "Gemini returned no usable answer"
        return None
    action = d.get("action") if d.get("action") in ("explain", "modify", "restore") else "explain"
    out = {"action": action, "answer": str(d["answer"]), "label": str(d.get("label") or "")[:100], "change_summary": str(d.get("change_summary") or "")[:300],
           "pct": max(0.0, min(100.0, _num(d.get("claim_at_risk_percent")))), "itc_adj": _clean(d.get("itc_adjustments")), "out_adj": _clean(d.get("output_adjustments")),
           "restore_version": int(_num(d.get("restore_version"))) or None,
           "engine": f"Gemini ({gemini.LAST_MODEL['name']}) + " + ("Vertex AI Search (managed RAG)" if rag_backend == "vertex-ai-search" else "local rule search (managed RAG not reachable)")}
    out["figures"] = f
    return out
