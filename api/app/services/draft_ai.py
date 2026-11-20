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
 "restore_version": number (restore only),
 "edited_tables": the COMPLETE updated draft document (same structure as CURRENT DRAFT: table_3_1, table_4, table_6, summary) - use this when the user asks to remove, add or rename a row, or to change a value directly (modify only)
}
Rules for you:
- Adjustments are measured from the ORIGINAL auto-draft figures in FIGURES, not from the current draft. The CURRENT DRAFT shows the adjustments already applied under summary.adjustments;
  repeat the ones the user wants to keep and add or change the new ones.
- claim_at_risk_percent already claims that share of the at-risk credit. Do NOT also add itc_adjustments for the same amounts: itc_adjustments are only for extra manual changes the user asks for
  (for example "reduce CGST credit by 3000"). Without such a request, itc_adjustments must be empty.
- For a direct edit ("remove the blocked row", "add a row", "set IGST output to 50000"), return edited_tables with exactly that change and everything else unchanged, and leave
  claim_at_risk_percent out. Do not invent figures the user did not ask for. The app recomputes the cash payable of every case from the output tax and ITC claimed, and Case A and Case B follow the (A) and At-risk rows of Table 4, so change only the row the user named.
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
           "edited_tables": d.get("edited_tables") if isinstance(d.get("edited_tables"), dict) else None,
           "engine": f"Gemini ({gemini.LAST_MODEL['name']}) + " + ("Vertex AI Search (managed RAG)" if rag_backend == "vertex-ai-search" else "local rule search (managed RAG not reachable)")}
    out["figures"] = f
    return out


def _heads(d) -> dict:
    return {h: round(max(0.0, _num((d or {}).get(h))), 2) for h in HEADS}


def sanitize_tables(new: dict, old: dict) -> tuple[dict | None, str]:
    """Checks an edited draft (from Gemini or from the manual editor) and rebuilds what is derived from it. Returns (tables, error).
    Numbers are non-negative and rounded; the cash payable of every case is recomputed as max(0, output tax - ITC claimed) per head."""
    try:
        t31, t4, t6 = new["table_3_1"], new["table_4"], new["table_6"]
        out = _heads(t31.get("tax"))
        rows = [{"label": (str(r.get("label", ""))[:120].strip() or "Row"), "tax": _heads(r.get("tax"))} for r in (t4.get("rows") or [])[:20] if isinstance(r, dict)]
        # Table 4 feeds Table 6: Case A claims the (A) row, Case B claims the (A) row plus the "At risk" row. When one of those rows was changed and the
        # case's own ITC was not changed in the same edit, the case follows the row. An ITC value the user typed into Table 6 is always kept.
        def row_of(rs, start):
            return next((r["tax"] for r in rs if r["label"].lower().startswith(start)), None)
        old_rows = [{"label": r["label"], "tax": _heads(r.get("tax"))} for r in (old.get("table_4") or {}).get("rows", [])]
        old_cases = {c["key"]: _heads(c.get("itc_claimed")) for c in (old.get("table_6") or {}).get("cases", [])}
        el_new, el_old = row_of(rows, "(a)"), row_of(old_rows, "(a)")
        ar_new, ar_old = row_of(rows, "at risk - not"), row_of(old_rows, "at risk - not")
        cases, seen = [], set()
        for c in (t6.get("cases") or [])[:6]:
            key = str(c.get("key", "?"))[:2]
            if key in seen:
                continue
            seen.add(key)
            itc = _heads(c.get("itc_claimed"))
            if itc == old_cases.get(key):  # the case's own ITC was not edited: let it follow Table 4
                if key == "A" and el_new is not None and el_old is not None and el_new != el_old:
                    itc = dict(el_new)
                elif key == "B" and el_new is not None and ar_new is not None and (el_new != el_old or ar_new != ar_old):
                    itc = {h: round(el_new[h] + ar_new[h], 2) for h in HEADS}
            cash = {h: round(max(0.0, out[h] - itc[h]), 2) for h in HEADS}
            cases.append({"key": key, "label": str(c.get("label", ""))[:120], "itc_claimed": itc, "cash": cash, "total": round(sum(cash.values()), 2)})
        if not cases:
            return None, "The draft must keep at least one payment case in Table 6."
        old_sum = old.get("summary") or {}
        sel = (new.get("summary") or {}).get("selected_case") or old_sum.get("selected_case") or cases[0]["key"]
        if sel not in seen:
            sel = cases[0]["key"]
        a = next((c for c in cases if c["key"] == "A"), None)
        b = next((c for c in cases if c["key"] == "B"), None)
        summary = {**old_sum, "selected_case": sel, "cash_saved_by_case_b": round(a["total"] - b["total"], 2) if a and b else old_sum.get("cash_saved_by_case_b", 0.0)}
        tables = {"table_3_1": {"title": str(t31.get("title") or old["table_3_1"]["title"])[:120], "taxable_value": round(max(0.0, _num(t31.get("taxable_value"))), 2), "tax": out},
                  "table_4": {"title": str(t4.get("title") or old["table_4"]["title"])[:120], "rows": rows},
                  "table_6": {"title": str(t6.get("title") or old["table_6"]["title"])[:120], "cases": cases}, "summary": summary}
        return tables, ""
    except (KeyError, TypeError, AttributeError) as exc:
        return None, f"The edited document was not in the expected shape ({type(exc).__name__}), so nothing was changed."


def diff_tables(old: dict, new: dict) -> list[str]:
    """Plain-language list of what changed between two drafts, written by code so it is always true."""
    lines: list[str] = []
    o, n = old["table_3_1"], new["table_3_1"]
    if abs(o["taxable_value"] - n["taxable_value"]) > 0.004:
        lines.append(f"Table 3.1 taxable value: ₹{o['taxable_value']:,.2f} → ₹{n['taxable_value']:,.2f}")
    for h in HEADS:
        if abs(o["tax"][h] - n["tax"][h]) > 0.004:
            lines.append(f"Table 3.1 {h.upper()} output tax: ₹{o['tax'][h]:,.2f} → ₹{n['tax'][h]:,.2f}")
    orows, nrows = {r["label"]: r for r in old["table_4"]["rows"]}, {r["label"]: r for r in new["table_4"]["rows"]}
    lines += [f"Table 4: removed the row \"{l}\"" for l in orows if l not in nrows]
    lines += [f"Table 4: added the row \"{l}\"" for l in nrows if l not in orows]
    for l in nrows:
        if l in orows:
            for h in HEADS:
                if abs(orows[l]["tax"][h] - nrows[l]["tax"][h]) > 0.004:
                    lines.append(f"Table 4 \"{l}\" {h.upper()}: ₹{orows[l]['tax'][h]:,.2f} → ₹{nrows[l]['tax'][h]:,.2f}")
    ocases, ncases = {c["key"]: c for c in old["table_6"]["cases"]}, {c["key"]: c for c in new["table_6"]["cases"]}
    lines += [f"Table 6: removed Case {k}" for k in ocases if k not in ncases]
    lines += [f"Table 6: added Case {k}" for k in ncases if k not in ocases]
    for k in ncases:
        if k in ocases:
            for h in HEADS:
                if abs(ocases[k]["itc_claimed"][h] - ncases[k]["itc_claimed"][h]) > 0.004:
                    lines.append(f"Table 6 Case {k} {h.upper()} ITC claimed: ₹{ocases[k]['itc_claimed'][h]:,.2f} → ₹{ncases[k]['itc_claimed'][h]:,.2f}")
    osel, nsel = (old.get("summary") or {}).get("selected_case") or "A", (new.get("summary") or {}).get("selected_case") or "A"  # a draft without a stored choice means Case A
    if osel != nsel:
        lines.append(f"Selected case: {osel} → {nsel}")
    return lines
