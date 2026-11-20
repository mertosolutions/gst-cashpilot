import pytest

H = {"X-Demo-User": "demo-owner"}


def ask(client, text, lang="en-IN", month="2026-10"):
    r = client.post("/api/v1/voice/query", json={"text": text, "lang": lang, "month": month}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def summary(client):
    return client.get("/api/v1/dashboard/summary", params={"month": "2026-10"}, headers=H).json()["current"]


def test_top_vendors(client):
    r = ask(client, "Which vendors are blocking my credit?")
    assert r["intent"] == "top_vendors" and r["results"]["items"][0]["name"] == "Kalyan Logistics"
    assert len(ask(client, "show me the top 3 vendors at risk")["results"]["items"]) == 3


def test_cash_payable(client):
    r = ask(client, "What is my cash payable this month?")
    assert r["intent"] == "cash_payable"
    cur = summary(client)  # other tests may have added invoices, so compare with the live dashboard
    assert [c["cash"] for c in r["results"]["items"]] == [cur["cash_safe"], cur["cash_full"]]
    from app.services.voice_search import inr
    assert inr(cur["cash_safe"]) in r["answer"] and inr(cur["cash_full"]) in r["answer"]
    assert inr(176642.5) == "₹1,76,643" and inr(145000) == "₹1,45,000" and inr(999) == "₹999" and inr(12345678) == "₹1,23,45,678"


def test_missing_in_2b_and_books(client):
    cur = summary(client)
    assert len(ask(client, "Show invoices missing in 2B")["results"]["items"]) == cur["missing_in_2b"]
    assert len(ask(client, "which invoices are missing in my books")["results"]["items"]) == cur["missing_in_books"]
    assert len(ask(client, "invoices not reported by suppliers")["results"]["items"]) == cur["missing_in_2b"]


def test_counts_and_blocked(client):
    r = ask(client, "How many invoices are blocked?")
    assert len(r["results"]["items"]) == 2 and r["filters"]["status"] == "blocked"


def test_vendor_and_amount_filters(client):
    r = ask(client, "Show at risk invoices from Kalyan")
    assert r["filters"]["vendor"] == "Kalyan Logistics"
    assert r["results"]["items"] and all(i["vendor"] == "Kalyan Logistics" and i["itc_status"] == "at_risk" for i in r["results"]["items"])
    big = ask(client, "at risk invoices above five thousand")
    assert big["filters"]["amount"]["value"] == 5000 and big["results"]["items"]
    assert all(i["at_risk"] >= 5000 for i in big["results"]["items"])
    assert all(i["at_risk"] >= 20000 for i in ask(client, "blocked invoices above 20k")["results"]["items"])


def test_explain_one_invoice(client):
    r = ask(client, "why is invoice MET-0037 at risk")
    assert r["intent"] == "explain_invoice" and "Section 16(2)(aa)" in r["answer"]


def test_month_words_and_unknown(client):
    assert ask(client, "cash payable in september")["month"] == "2026-09"
    assert ask(client, "blah blah")["intent"] == "unknown"


def test_other_language_needs_gemini_but_does_not_crash(client):
    r = ask(client, "Which vendors are blocking my credit?", lang="hi-IN")
    assert r["language"] == "hi" and r["notes"] and r["intent"] == "top_vendors"  # English words still parse; the note explains translation


def test_suggestions_are_built_from_the_data(client):
    r = client.get("/api/v1/voice/suggestions", params={"month": "2026-10"}, headers=H)
    assert r.status_code == 200 and any("Kalyan Logistics" in s for s in r.json())
