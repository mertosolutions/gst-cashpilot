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


def test_greeting_is_answered_locally_with_example_questions(client):
    r = ask(client, "hello")
    assert r["intent"] == "help" and r["results"]["type"] == "help" and len(r["results"]["items"]) >= 3
    assert ask(client, "what can you do")["intent"] == "help"
    assert ask(client, "hello, which vendors block my credit")["intent"] == "top_vendors"  # a greeting plus a real question is still a question


def test_top_vendor_by_purchase_is_ranked_by_spend_not_risk(client):
    r = ask(client, "tell me the top most vendor I have purchased")
    assert r["intent"] == "top_vendors_by_purchase" and r["results"]["metric"] == "spend"
    spends = [v["spend"] for v in r["results"]["items"]]
    assert spends == sorted(spends, reverse=True) and "purchases" in r["answer"]
    assert ask(client, "which vendors are blocking my credit")["results"]["metric"] == "at_risk"


def test_buyer_questions_get_an_honest_scope_answer(client):
    r = ask(client, "can you just tell me who is the buyer from me")
    assert r["intent"] == "customers_scope" and "GSTR-1" in r["answer"] and "buyer on every purchase invoice" in r["answer"]
    assert ask(client, "what is my gstin")["intent"] == "about_business"


def test_copilot_fallback_never_crashes_and_matches_the_chat_numbers(client):
    for q in ("hello", "tell me something random about the weather", "who is the buyer"):
        r = client.post("/api/v1/copilot/ask", json={"question": q, "month": "2026-10"}, headers=H)
        assert r.status_code == 200, (q, r.text)
    cash = client.post("/api/v1/copilot/ask", json={"question": "what is my cash payable", "month": "2026-10"}, headers=H).json()["answer"]
    chat = ask(client, "what is my cash payable")["answer"]
    assert cash == chat  # one engine, one answer
    assert "could not match" in client.post("/api/v1/copilot/ask", json={"question": "weather today", "month": "2026-10"}, headers=H).json()["answer"]


def test_leading_vendor_and_only_one_vendor_return_a_single_vendor(client):
    for q in ("WHO IS THE LEADING VENDOR", "CHOOSE ONLY 1 VENDOR", "Choose any one vendor.", "who is the top vendor"):
        r = ask(client, q)
        assert r["intent"] in ("top_vendors", "top_vendors_by_purchase") and len(r["results"]["items"]) == 1, q  # "top vendor" alone means by purchases
        assert r["results"]["items"][0]["name"] in r["answer"], q
    assert len(ask(client, "Which vendors are blocking my credit?")["results"]["items"]) > 1  # the plural still lists several


def test_why_question_explains_the_rule_and_corrects_the_premise(client):
    r = ask(client, "Why is the largest at-risk invoice blocked under GST rules?")
    assert r["intent"] == "explain_invoice" and len(r["results"]["items"]) == 1
    assert "not blocked" in r["answer"].lower() and "At risk" in r["answer"] and "Section 16" in r["answer"]


def test_largest_amount_matches_the_list(client):
    r = ask(client, "Show at risk invoices")
    top = r["results"]["items"][0]
    from app.services.voice_search import inr
    assert inr(top["at_risk"]) in r["answer"]  # the spoken 'largest' amount is the at-risk amount the list shows
