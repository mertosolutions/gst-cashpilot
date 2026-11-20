"""Voice data search. The browser turns speech into text; this service understands the question and answers it from the saved results.
Understanding is plain code (intent + filters), so answers are exact and work offline. Gemini is used only to translate when the
user speaks another language, and to translate the spoken reply back. Nothing here changes data."""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Vendor
from app.services import analytics, gemini, tax
from app.services.util import clean_invoice_no, money, month_label

LANG_NAMES = {"en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu", "kn": "Kannada", "ml": "Malayalam", "mr": "Marathi", "bn": "Bengali", "gu": "Gujarati"}
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
MONTHS.update({"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12})
WORD_NUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
            "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100}
UNIT = {"k": 1e3, "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7}
GENERIC = {"pvt", "ltd", "private", "limited", "traders", "services", "supplies", "the", "and", "company", "co"}


def inr(v: float) -> str:
    """Indian grouping: 176643 -> ₹1,76,643."""
    neg = v < 0
    n = f"{int(abs(v) + 0.5):d}"  # round half up (Python's round() is banker's rounding)
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        n = ",".join(parts + [tail])
    return ("-" if neg else "") + "₹" + n


def _words_to_digits(t: str) -> str:
    """'fifty thousand' -> '50 thousand', 'ten' -> '10' so the amount regex can read spoken numbers."""
    def repl(m: re.Match) -> str:
        words = m.group(0).split()
        total = 0
        for w in words:
            total += WORD_NUM[w]
        return str(total)
    return re.sub(r"\b(?:(?:%s)(?:\s+(?:%s))*)\b" % ("|".join(WORD_NUM), "|".join(WORD_NUM)), repl, t)


def parse_amount(t: str) -> tuple[str, float] | None:
    t = _words_to_digits(t)
    m = re.search(r"(above|over|more than|greater than|at least|exceeding|bigger than)\s*(?:rs\.?|₹|rupees)?\s*([\d,]+(?:\.\d+)?)\s*(k|thousand|lakhs?|lacs?|crores?|cr)?\b", t)
    op = "gte" if m else None
    if not m:
        m = re.search(r"(below|under|less than|lower than|at most|smaller than)\s*(?:rs\.?|₹|rupees)?\s*([\d,]+(?:\.\d+)?)\s*(k|thousand|lakhs?|lacs?|crores?|cr)?\b", t)
        op = "lte" if m else None
    if not m:
        return None
    return op, float(m.group(2).replace(",", "")) * UNIT.get((m.group(3) or "").lower(), 1)


def parse_top_n(t: str) -> int | None:
    t = _words_to_digits(t)
    m = re.search(r"\b(?:top|first|biggest|largest|worst)\s*(\d{1,2})\b", t)
    if m:
        return int(m.group(1))
    # "only 1 vendor", "any one vendor", "just one", "a single supplier", "the leading vendor", "who is the top vendor"
    if re.search(r"\b(?:only|just|any|single)\s*(?:1|one|a)?\s*(?:vendor|supplier|invoice)s?\b|\b(?:only|just|any)\s*(?:1|one)\b|\b(?:1|one)\s+(?:vendor|supplier|invoice)\b", t):
        return 1
    if re.search(r"\b(?:leading|main|biggest|largest|top|worst|number 1|no\.? 1)\s+(?:vendor|supplier)\b(?!s)|\bwho\s+is\s+(?:the\s+)?(?:leading|main|biggest|largest|worst)\b", t):
        return 1
    return None


def parse_month(t: str, available: list[str], current: str) -> str:
    if re.search(r"\b(last|previous|prior) month\b", t):
        y, mo = int(current[:4]), int(current[5:])
        mo -= 1
        if mo == 0:
            y, mo = y - 1, 12
        key = f"{y:04d}-{mo:02d}"
        return key if key in available else current
    for name, num in MONTHS.items():
        if re.search(rf"\b{name}\b", t):
            cands = [m for m in available if int(m[5:]) == num]
            if cands:
                return cands[-1]
    return current


def find_vendor(db: Session, business_id: str, t: str) -> Vendor | None:
    best, score = None, 0
    words = set(re.findall(r"[a-z0-9]+", t))
    for v in db.query(Vendor).filter_by(business_id=business_id).all():
        toks = [w for w in re.findall(r"[a-z0-9]+", v.name.lower()) if w not in GENERIC and len(w) >= 3]
        hit = sum(1 for w in toks if w in words)
        if hit and hit / max(1, len(toks)) >= 0.5 and hit > score:
            best, score = v, hit
    return best


def find_invoice_no(t_raw: str, known: set[str]) -> str | None:
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9/\-]{2,}", t_raw):
        c = clean_invoice_no(tok)
        if c in known:
            return tok
    return None


def _translate(text: str, direction: str, lang: str) -> str | None:
    """direction 'to_en' or 'from_en'. Returns None when Gemini is unavailable or fails."""
    if not gemini.available():
        return None
    name = LANG_NAMES.get(lang, lang)
    prompt = (f"Translate this {name} question about GST invoices into English. Keep numbers, vendor names and invoice numbers exactly. Output only the translation.\n\n{text}"
              if direction == "to_en" else
              f"Translate this into {name}. Keep numbers, rupee amounts, vendor names and invoice numbers unchanged. Output only the translation.\n\n{text}")
    try:
        return gemini.generate_text(prompt) or None
    except Exception as exc:  # noqa: BLE001
        if gemini.is_quota_error(exc):
            gemini.mark_quota_hit()
        return None


def suggestions(db: Session, business_id: str, month: str) -> list[str]:
    v = analytics.vendors(db, business_id, month, window=1, sort="at_risk", limit=1)
    c = analytics.month_metrics(db, business_id, month)
    out = ["Which vendors are blocking my credit?", "What is my cash payable?", f"How many invoices are missing in 2B in {month_label(month).split()[0]}?"]
    if v["items"]:
        first = v["items"][0]["name"]
        out.append(f"Show at risk invoices from {first}")
        step = 5000 if c["at_risk"] < 100000 else 20000
        out.append(f"Show at risk invoices above {step // 1000} thousand")
    if c["blocked"]:
        out.append("Which invoices are blocked?")
    return out


def answer(db: Session, business_id: str, text: str, month: str, lang: str = "en-IN") -> dict:
    code = lang.split("-")[0].lower()
    original = text.strip()
    notes: list[str] = []
    english = original
    engine = "local intent parser"
    if code != "en":
        tr = _translate(original, "to_en", code)
        if tr:
            english, engine = tr.strip(), "Gemini translation + local intent parser"
        else:
            notes.append(f"Speaking {LANG_NAMES.get(code, code)} needs Gemini to translate, and Gemini is not available now. English works without it.")
    t = english.lower()
    available = analytics.available_months(db, business_id)
    month = parse_month(t, available, month)
    f: dict = {"month": month}

    # known invoice numbers of this month, to recognise 'invoice MET-0037'
    items_all = analytics.reconciliation_items(db, business_id, month, page_size=200)["items"]
    known = {clean_invoice_no(i["invoice_no"]): i for i in items_all}
    inv_tok = find_invoice_no(english, set(known))

    status = next((s for s, ks in (("at_risk", ("at risk", "risky", "not confirmed", "at-risk")), ("blocked", ("blocked", "block credit", "cannot claim", "17(5)")),
                                   ("eligible", ("eligible", "claimable", "can claim", "safe to claim"))) if any(k in t for k in ks)), None)
    match = None
    if re.search(r"(missing|absent|not)\s+(?:in|from|reported in|filed in|on)\s+(?:the\s+|my\s+|our\s+)?(?:gstr[\s-]?)?(?:2b|2 b)\b|not reported|not filed|didn'?t file|has not filed", t):
        match = "missing_in_2b"
    elif re.search(r"(missing|absent|not)\s+(?:in|from)\s+(?:the\s+|my\s+|our\s+)?(?:purchase\s+)?(?:books|register)\b|not in my purchase", t):
        match = "missing_in_books"
    elif re.search(r"mismatch|amount difference|different amount|does not match|doesn'?t match", t):
        match = "amount_mismatch"
    elif re.search(r"\bmatched\b|all good|no issue", t):
        match = "matched"
    vendor = find_vendor(db, business_id, t)
    amount = parse_amount(t)
    top_n = parse_top_n(t)
    wants_cash = bool(re.search(r"\b(cash|payable|how much (?:do i|will i|to) pay|pay)\b", t)) and not (status or match or vendor or inv_tok)
    wants_vendors = bool(re.search(r"\b(vendors?|suppliers?)\b", t)) and not vendor and not inv_tok and not match and (status in (None, "at_risk", "blocked"))
    wants_count = bool(re.search(r"\b(how many|count|number of)\b", t))
    risk_cue = bool(re.search(r"block|risk|credit|itc|claim|unconfirmed|not confirmed|not filed|mismatch", t)) or status in ("at_risk", "blocked")
    by_spend = bool(re.search(r"purchas|bought|\bbuy\b|spend|spent|biggest|largest|top supplier|top vendor|most from", t)) and not risk_cue
    asks_customers = bool(re.search(r"\b(buyers?|customers?|clients?|who bought|sold to|sales to|who (?:do|did) i sell)\b", t)) and not vendor
    asks_business = bool(re.search(r"\b(my gstin|my business|my company|company name|who am i|business name|my name)\b", t))
    if status:
        f["status"] = status
    if match:
        f["match"] = match
    if vendor:
        f["vendor"] = vendor.name
    if amount:
        f["amount"] = {"op": amount[0], "value": amount[1]}
    if inv_tok:
        f["invoice"] = inv_tok

    res: dict = {"type": "none", "items": []}
    if re.match(r"^\s*(hi|hii|hello|hey|namaste|vanakkam|good (morning|afternoon|evening)|help|what can you do|how (do|does) (you|this) work|who are you)\b", t) and not (status or match or vendor or inv_tok or wants_cash or wants_vendors or wants_count or amount):
        intent = "help"
        res = {"type": "help", "items": suggestions(db, business_id, month)[:4]}
        spoken = "Hi, I am CashPilot. Ask me about your vendors, at-risk or blocked invoices, invoices missing in GSTR-2B, or your cash payable."
    elif inv_tok:
        row = known[clean_invoice_no(inv_tok)]
        d = analytics.reconciliation_detail(db, business_id, row["match_id"]) or {}
        dec = d.get("decision")
        res = {"type": "invoices", "items": [row]}
        if dec:
            spoken = f"Invoice {row['invoice_no']} from {row['vendor']} is {dec['status'].replace('_', ' ')}. {dec['reason']}" + (f" Rule: {dec['citation']}." if dec.get("citation") else "")
        else:
            spoken = f"Invoice {row['invoice_no']} from {row['vendor']} is {row['match_type'].replace('_', ' ')}, and it has no ITC decision because it is not in your books."
        intent = "explain_invoice"
    elif wants_cash:
        fg = tax.figures(db, business_id, month)
        res = {"type": "cash", "items": [{"case": "A", "label": "Claim only eligible credit", "cash": fg["cash_a"]}, {"case": "B", "label": "Also claim at-risk credit", "cash": fg["cash_b"]}]}
        spoken = (f"For {month_label(month)}, your cash payable is {inr(fg['cash_a'])} if you claim only the eligible credit, and {inr(fg['cash_b'])} if you also claim "
                  f"the at-risk credit. The difference of {inr(fg['cash_a'] - fg['cash_b'])} is credit that is not confirmed by GSTR-2B.")
        intent = "cash_payable"
    elif asks_customers or asks_business:
        from app.models import Business
        b = db.get(Business, business_id)
        intent = "about_business" if asks_business and not asks_customers else "customers_scope"
        if intent == "about_business":
            spoken = f"Your business is {b.legal_name}, GSTIN {b.gstin}. You are the buyer on every purchase invoice in CashPilot."
        else:
            spoken = (f"You, {b.legal_name}, are the buyer on every purchase invoice here. CashPilot works with your purchases and GSTR-2B, so it knows your sales only as monthly totals, "
                      "not who your customers are (that is GSTR-1 data). I can tell you about your vendors, invoices, ITC and cash payable.")
        res = {"type": "help", "items": suggestions(db, business_id, month)[:3]}
    elif wants_vendors or by_spend:
        n = top_n or 5
        sort = "blocked" if status == "blocked" else ("spend" if by_spend else "at_risk")
        v = analytics.vendors(db, business_id, month, window=1, sort=sort, limit=n)
        rows = [r for r in v["items"] if r[sort] > 0]
        res = {"type": "vendors", "items": rows, "metric": sort}
        if sort == "spend":
            intent = "top_vendors_by_purchase"
            spoken = (f"Your top vendors by purchases in {month_label(month)} are: " + ", ".join(f"{r['name']} {inr(r['spend'])}" for r in rows[:3]) + "." if rows
                      else f"There are no purchases in {month_label(month)}.")
        elif rows and n == 1:
            r0 = rows[0]
            total = analytics.month_metrics(db, business_id, month)["blocked" if sort == "blocked" else "at_risk"]
            share = f" That is {r0[sort] / total * 100:.0f} percent of all {'blocked' if sort == 'blocked' else 'at-risk'} credit." if total else ""
            matched = f" Only {r0['matched_pct']:.0f} percent of its invoices match GSTR-2B." if r0.get("matched_pct") is not None else ""
            spoken = f"The leading vendor in {month_label(month)} is {r0['name']}, holding {inr(r0[sort])} of {'blocked' if sort == 'blocked' else 'at-risk'} credit.{share}{matched}"
        elif rows:
            parts = [f"{r['name']} {inr(r[sort])}" for r in rows[:3]]
            spoken = f"In {month_label(month)}, {'blocked' if sort == 'blocked' else 'at-risk'} credit is held mostly by: " + ", ".join(parts) + (f". The top three hold {v['top3_share']:.0f} percent of the at-risk credit." if sort == "at_risk" else ".")
        else:
            spoken = f"No vendors hold {'blocked' if sort == 'blocked' else 'at-risk'} credit in {month_label(month)}."
        if sort != "spend":
            intent = "top_vendors"
    elif status or match or vendor or amount or wants_count:
        lst = analytics.reconciliation_items(db, business_id, month, match_type=match, itc_status=status, vendor_gstin=vendor.gstin if vendor else None,
                                             sort="at_risk" if status != "eligible" else "claimable", page_size=200)
        rows = lst["items"]
        field = {"at_risk": "at_risk", "blocked": "blocked", "eligible": "claimable"}.get(status or "", "taxable")
        if amount:
            rows = [r for r in rows if (r[field] >= amount[1] if amount[0] == "gte" else r[field] <= amount[1])]
        if top_n:
            rows = rows[:top_n]
        asks_why = bool(re.search(r"\b(why|explain|reason|how come|because)\b", t)) and bool(rows) and not wants_count
        if asks_why:
            top = rows[0]
            d = analytics.reconciliation_detail(db, business_id, top["match_id"]) or {}
            dec = d.get("decision")
            label = {"at_risk": "At risk", "blocked": "Blocked", "eligible": "Eligible"}
            res = {"type": "invoices", "items": [top]}
            if dec:
                real = label.get(dec["status"], dec["status"])
                premise = ""
                if "blocked" in t and dec["status"] != "blocked":
                    premise = f"It is not blocked. It is {real}, which means the credit is held back for now, not lost. "
                elif status == "blocked" and dec["status"] != "blocked":
                    premise = f"It is {real}, not Blocked. "
                spoken = (f"The largest invoice is {top['invoice_no']} from {top['vendor']} ({inr(top[field])}). {premise}"
                          f"Status: {real}. {dec['reason']}" + (f" Rule: {dec['citation']}." if dec.get("citation") else ""))
            else:
                spoken = (f"The largest invoice is {top['invoice_no']} from {top['vendor']}. It is {top['match_type'].replace('_', ' ')} and has no ITC decision because it is not in your books.")
            intent = "explain_invoice"
        else:
            res = {"type": "invoices", "items": rows}
            what = " ".join(x for x in [(status or "").replace("_", " "), (match or "").replace("_", " ")] if x) or "all"
            who = f" from {vendor.name}" if vendor else ""
            thr = f" with {field.replace('claimable', 'eligible')} amount {'above' if amount and amount[0] == 'gte' else 'below'} {inr(amount[1])}" if amount else ""
            total_risk = sum(r["at_risk"] for r in rows)
            if wants_count and not rows:
                spoken = f"There are no {what} invoices{who}{thr} in {month_label(month)}."
            elif not rows:
                spoken = f"I found no {what} invoices{who}{thr} in {month_label(month)}."
            else:
                spoken = f"I found {len(rows)} {what} invoice{'s' if len(rows) != 1 else ''}{who}{thr} in {month_label(month)}."
                if total_risk:
                    spoken += f" Together, {inr(total_risk)} is at risk."
                top = rows[0]
                spoken += f" The largest is {top['vendor']}, invoice {top['invoice_no']}, with {'a taxable value of ' if field == 'taxable' else ''}{inr(top[field])}{' at risk' if field == 'at_risk' else ''}."
            intent = "count_invoices" if wants_count else "search_invoices"
    else:
        intent = "unknown"
        spoken = "I did not understand that. You can ask about vendors, at-risk or blocked invoices, invoices missing in 2B, a vendor's invoices, or your cash payable."

    out = {"transcript": original, "english": english if english != original else None, "language": code, "month": month, "intent": intent, "filters": f,
           "answer": spoken, "results": res, "engine": engine, "notes": notes, "spoken": spoken, "spoken_language": "en"}
    if code != "en":
        back = _translate(spoken, "from_en", code)
        if back:
            out["spoken"], out["spoken_language"] = back.strip(), code
    return out
