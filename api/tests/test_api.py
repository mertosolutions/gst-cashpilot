import pytest

H = {"X-Demo-User": "demo-owner"}
# the UI lists two samples; every sample file can still be processed by name
NAMES = {"matches_gstr2b": "scan_matches_gstr2b_x902.pdf", "wrong_total": "scan_wrong_total_x901.pdf", "new_invoice": "scan_new_invoice_not_in_gstr2b.pdf", "igst_not_in_2b": "gst_invoice_2_igst_not_in_2b.pdf"}


def get(client, path, **params):
    r = client.get(f"/api/v1{path}", params=params, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_october_matches_the_documented_answers(client):
    s = get(client, "/dashboard/summary", month="2026-10")["current"]
    assert (s["invoices"], s["matched"], s["amount_mismatch"], s["missing_in_2b"], s["missing_in_books"]) == (50, 38, 5, 7, 3)
    assert s["cash_safe"] == 176642.5 and s["cash_full"] == 145000.0 and s["at_risk"] == 31642.5


def test_dashboard_has_kpis_series_and_insights(client):
    d = get(client, "/dashboard/summary", month="2026-10")
    assert d["kpis"][0]["key"] == "purchase_total"
    assert len(d["kpis"][0]["series"]) == 6
    assert get(client, "/dashboard/insights", month="2026-10")
    assert len(get(client, "/dashboard/trends", month="2026-10", months=6)) == 6


def test_vendor_view_is_flexible(client):
    by_risk = get(client, "/vendors", month="2026-10", sort="at_risk", limit=3)
    assert len(by_risk["items"]) == 3
    assert by_risk["items"][0]["at_risk"] >= by_risk["items"][1]["at_risk"]
    by_spend = get(client, "/vendors", month="2026-10", sort="spend", limit=5, window=3)
    assert by_spend["window"] == 3 and by_spend["items"][0]["spend"] >= by_spend["items"][-1]["spend"]
    high = get(client, "/vendors", month="2026-10", risk="high", limit=0)
    assert all(v["risk_level"] == "high" for v in high["items"])


def test_every_decision_has_a_rule_and_detail(client):
    items = get(client, "/reconciliation", month="2026-10", page_size=200)["items"]
    decided = [i for i in items if i["itc_status"]]
    assert len(decided) == 50 and all(i["citation"] for i in decided)
    blocked = [i for i in decided if i["itc_status"] == "blocked"]
    assert len(blocked) == 2 and all("17(5)" in i["citation"] for i in blocked)
    detail = get(client, f"/reconciliation/{items[0]['match_id']}")
    assert detail["trace"] and detail["passages"]


def test_draft_and_pdf(client):
    d = get(client, "/draft", month="2026-10")
    cases = d["tables"]["table_6"]["cases"]
    assert cases[0]["total"] == 176642.5 and cases[1]["total"] == 145000.0
    r = client.get("/api/v1/draft/pdf", params={"month": "2026-10"}, headers=H)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_processing_layers(client):
    run = get(client, "/pipeline/latest", month="2026-10")
    assert [s["layer"] for s in run["stages"]] == [1, 2, 3, 4, 5, 6]
    assert run["status"] in ("ok", "warn")


def test_users_are_isolated_from_each_other(client):
    """A new user gets their own business (seeded with a private copy of the demo data), never the first user's rows."""
    mine = client.get("/api/v1/me", headers=H).json()
    other_h = {"X-Demo-User": "someone-else"}
    theirs = client.get("/api/v1/me", headers=other_h).json()
    assert mine["business_id"] != theirs["business_id"]
    v1 = client.get("/api/v1/vendors", params={"month": "2026-10", "limit": 0}, headers=H).json()["items"]
    v2 = client.get("/api/v1/vendors", params={"month": "2026-10", "limit": 0}, headers=other_h).json()["items"]
    assert {v["vendor_id"] for v in v1}.isdisjoint({v["vendor_id"] for v in v2})
    # a change made by the other user does not touch the first user's books
    samples = client.get("/api/v1/scans/samples", headers=other_h).json()
    new = {"name": NAMES["new_invoice"]}
    scan = client.post(f"/api/v1/scans/samples/{new['name']}", headers=other_h).json()
    f = scan["fields"]
    body = {k: f[k] for k in ("supplier_name", "supplier_gstin", "invoice_no", "invoice_date", "taxable_value", "igst", "cgst", "sgst", "category")}
    assert client.post(f"/api/v1/scans/{scan['id']}/confirm", json=body, headers=other_h).status_code == 200
    assert get(client, "/dashboard/summary", month="2026-10")["current"]["invoices"] == 50


def test_scanner_flow_and_impact(client):
    samples = client.get("/api/v1/scans/samples", headers=H).json()
    ok = {"name": NAMES["matches_gstr2b"]}
    scan = client.post(f"/api/v1/scans/samples/{ok['name']}", headers=H)
    assert scan.status_code == 200, scan.text
    s = scan.json()
    assert s["fields"]["supplier_gstin"] and all(c["status"] != "fail" for c in s["checks"])
    f = s["fields"]
    body = {k: f[k] for k in ("supplier_name", "supplier_gstin", "invoice_no", "invoice_date", "taxable_value", "igst", "cgst", "sgst", "category")}
    done = client.post(f"/api/v1/scans/{s['id']}/confirm", json=body, headers=H)
    assert done.status_code == 200, done.text
    assert done.json()["match_type"] == "matched"  # it resolves a 'missing in books' entry
    assert done.json()["after"]["missing_in_books"] == done.json()["before"]["missing_in_books"] - 1
    again = client.post(f"/api/v1/scans/{s['id']}/confirm", json=body, headers=H)
    assert again.status_code == 409


def test_bad_scan_fails_validation(client):
    samples = client.get("/api/v1/scans/samples", headers=H).json()
    bad = {"name": NAMES["wrong_total"]}
    s = client.post(f"/api/v1/scans/samples/{bad['name']}", headers=H).json()
    assert any(c["key"] == "total" and c["status"] == "fail" for c in s["checks"])


def test_copilot_without_gemini_uses_the_grounded_fallback(client):
    """With no Gemini key the copilot answers from the decision engine instead of failing (see ask_copilot in agents/runner.py)."""
    r = client.post("/api/v1/copilot/ask", json={"question": "Which vendors block my credit?", "month": "2026-10"}, headers=H)
    assert r.status_code == 200
    assert "Fallback" in r.json()["agent"] and r.json()["answer"].strip()


def test_adk_agents_build():
    from app.agents.definitions import build_agents
    root, extraction = build_agents()
    assert {a.name for a in root.sub_agents} >= {"tax_reconciliation_agent", "vendor_communication_agent", "gst_legal_rag_agent"}
    assert extraction.name == "extraction_agent"


def _vat_pdf(tmp_path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    p = tmp_path / "vat_invoice.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    for i, ln in enumerate(["Invoice No: 51109301", "Invoice Date: 07/03/2023", "TechVision Distributors Pvt Ltd", "GSTIN 27AABCT1234F1Z5",
                            "Description Qty UM Net Worth", "VAT % 10%", "INR 1,676,970", "Total 1,844,673"]):
        c.drawString(60, 800 - i * 24, ln)
    c.save()
    return p


def test_non_gst_invoice_cannot_be_saved(client, tmp_path):
    p = _vat_pdf(tmp_path)
    with open(p, "rb") as fh:
        r = client.post("/api/v1/scans", files={"file": (p.name, fh, "application/pdf")}, headers=H)
    assert r.status_code == 200, r.text
    s = r.json()
    keys = {c["key"]: c["status"] for c in s["checks"]}
    assert keys["gst_invoice"] == "fail" and keys["amounts"] == "fail"
    f = s["fields"]
    body = {k: f[k] for k in ("supplier_name", "supplier_gstin", "invoice_no", "invoice_date", "taxable_value", "igst", "cgst", "sgst", "category")}
    done = client.post(f"/api/v1/scans/{s['id']}/confirm", json=body, headers=H)
    assert done.status_code == 422 and "Fix these checks" in done.text


def test_undo_removes_a_confirmed_scan(client):
    samples = client.get("/api/v1/scans/samples", headers=H).json()
    new = {"name": NAMES["new_invoice"]}
    s = client.post(f"/api/v1/scans/samples/{new['name']}", headers=H).json()
    f = s["fields"]
    body = {k: f[k] for k in ("supplier_name", "supplier_gstin", "invoice_no", "invoice_date", "taxable_value", "igst", "cgst", "sgst", "category")}
    done = client.post(f"/api/v1/scans/{s['id']}/confirm", json=body, headers=H).json()
    assert done["itc_status"] == "at_risk" and done["after"]["invoices"] == done["before"]["invoices"] + 1
    assert client.post(f"/api/v1/scans/{s['id']}/undo", headers=H).status_code == 200
    now = get(client, "/dashboard/summary", month="2026-10")["current"]
    assert now["invoices"] == done["before"]["invoices"]


def test_a_gst_return_summary_is_not_accepted_as_an_invoice(client, tmp_path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    p = tmp_path / "gstr3b_draft.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    for i, ln in enumerate(["GSTR-3B expected draft - October 2026", "GSTIN 27AAAAA0000A1Z5 Return period 102026", "Taxable value 1,850,000.00 IGST 53,777.00 CGST 94,751.00",
                            "Total cash payable, Case A 176,642.50"]):
        c.drawString(60, 800 - i * 24, ln)
    c.save()
    with open(p, "rb") as fh:
        r = client.post("/api/v1/scans", files={"file": (p.name, fh, "application/pdf")}, headers=H)
    s = r.json()
    keys = {c["key"]: c["status"] for c in s["checks"]}
    assert keys["is_invoice"] == "fail"
    assert s["fields"]["supplier_gstin"] == ""  # the business's own GSTIN is not a supplier
    assert "GST return" in next(c["detail"] for c in s["checks"] if c["key"] == "is_invoice")


def test_delete_a_scan_and_a_confirmed_scan(client):
    samples = client.get("/api/v1/scans/samples", headers=H).json()
    wrong = {"name": NAMES["wrong_total"]}
    s1 = client.post(f"/api/v1/scans/samples/{wrong['name']}", headers=H).json()
    r = client.delete(f"/api/v1/scans/{s1['id']}", headers=H)
    assert r.status_code == 200 and r.json()["removed_from_books"] is False
    assert all(x["id"] != s1["id"] for x in client.get("/api/v1/scans", headers=H).json())
    assert client.delete(f"/api/v1/scans/{s1['id']}", headers=H).status_code == 404
    # a scan that is already in the books: deleting it removes the invoice too
    before = get(client, "/dashboard/summary", month="2026-10")["current"]["invoices"]
    new = {"name": NAMES["igst_not_in_2b"]}
    s2 = client.post(f"/api/v1/scans/samples/{new['name']}", headers=H).json()
    f = s2["fields"]
    body = {k: f[k] for k in ("supplier_name", "supplier_gstin", "invoice_no", "invoice_date", "taxable_value", "igst", "cgst", "sgst", "category")}
    assert client.post(f"/api/v1/scans/{s2['id']}/confirm", json=body, headers=H).status_code == 200
    assert get(client, "/dashboard/summary", month="2026-10")["current"]["invoices"] == before + 1
    d = client.delete(f"/api/v1/scans/{s2['id']}", headers=H).json()
    assert d["removed_from_books"] is True
    assert get(client, "/dashboard/summary", month="2026-10")["current"]["invoices"] == before


def test_two_curated_samples_are_listed(client):
    r = client.get("/api/v1/scans/samples", headers=H).json()
    assert len(r) == 2 and all(x["title"] and x["description"] for x in r)


def test_vendor_pages_of_five(client):
    p1 = get(client, "/vendors", month="2026-10", limit=5, offset=0)
    p2 = get(client, "/vendors", month="2026-10", limit=5, offset=5)
    assert len(p1["items"]) == 5 and p1["total_matching"] >= 10
    assert {v["vendor_id"] for v in p1["items"]}.isdisjoint({v["vendor_id"] for v in p2["items"]})


def test_trend_still_charts_for_the_first_month(client):
    """Selecting the earliest month used to leave the trend empty (nothing before it). The window now starts at the first month."""
    t = get(client, "/dashboard/trends", month="2026-05", months=3)
    assert [m["month"] for m in t] == ["2026-05", "2026-06", "2026-07"]
    assert [m["month"] for m in get(client, "/dashboard/trends", month="2026-10", months=3)] == ["2026-08", "2026-09", "2026-10"]
    assert [m["month"] for m in get(client, "/dashboard/trends", month="2026-07", months=3)] == ["2026-05", "2026-06", "2026-07"]
    assert len(get(client, "/dashboard/trends", month="2026-05", months=6)) == 6
    ins = get(client, "/dashboard/insights", month="2026-05")
    assert isinstance(ins, list)  # no crash when there is no previous month


def test_rules_endpoint_lists_decision_rules_and_passages(client):
    r = get(client, "/pipeline/rules", month="2026-10")
    keys = [d["key"] for d in r["decision_rules"]]
    assert keys[:3] == ["not_in_2b", "itc_not_available", "blocked_category"] and keys[-1] == "no_rule_found"
    assert len(r["passages"]) == 15 and all(p["citation"] and p["body"] for p in r["passages"])
    assert sum(d["used"] for d in r["decision_rules"]) == r["invoices_checked"]
    assert any("17(5)" in p["citation"] and p["used"] > 0 for p in r["passages"])  # the blocked invoices cite Section 17(5)
    assert r["needs_ca_review"] is True


def test_dashboard_cache_is_cleared_after_a_write(client):
    from app.core import cache
    a = get(client, "/dashboard/summary", month="2026-10")
    assert get(client, "/dashboard/summary", month="2026-10") == a  # second call served from the cache
    assert cache._store  # something is cached
    client.post("/api/v1/pipeline/run", params={"month": "2026-10"}, headers=H)
    assert not any(k[0] == "summary" for k in cache._store)  # the write cleared it


def test_real_user_starts_blank_and_builds_from_own_upload(client):
    """A Google sign-in gets an empty workspace (no demo data); the GSTIN is learned from the user's own GSTR-2B."""
    from pathlib import Path
    from app.core.database import SessionLocal
    from app.core.security import CurrentUser, get_business
    from app.services import analytics
    with SessionLocal() as db:
        b = get_business(CurrentUser(uid="google-blank-user-1", name="New Owner", demo=False), db)
        assert b.gstin == "" and b.legal_name == "New Owner"
        assert analytics.available_months(db, b.id) == []
    sample = Path(__file__).resolve().parents[1] / "app/data/sample"
    with SessionLocal() as db:
        from app.services import ingest
        b = get_business(CurrentUser(uid="google-blank-user-1", name="New Owner", demo=False), db)
        ingest.ingest_gstr2b(db, b, (sample / "GSTR-2B_oct2026_dummy.xlsx").read_bytes(), "g.xlsx")
        ingest.ingest_purchase_register(db, b, (sample / "purchase_register_oct2026.csv").read_bytes(), "r.csv")
        assert b.gstin == "27AAAAA0000A1Z5"
        assert analytics.available_months(db, b.id) == ["2026-10"]


def test_delete_all_data_blanks_only_my_workspace(client):
    from app.core.database import SessionLocal
    from app.core.security import CurrentUser, get_business
    from app.services import analytics, ingest
    from pathlib import Path
    sample = Path(__file__).resolve().parents[1] / "app/data/sample"
    with SessionLocal() as db:
        b = get_business(CurrentUser(uid="google-wipe-user-1", name="Wipe Me", demo=False), db)
        ingest.ingest_gstr2b(db, b, (sample / "GSTR-2B_oct2026_dummy.xlsx").read_bytes(), "g.xlsx")
        ingest.ingest_purchase_register(db, b, (sample / "purchase_register_oct2026.csv").read_bytes(), "r.csv")
        assert analytics.available_months(db, b.id) == ["2026-10"]
    before = client.get("/api/v1/dashboard/summary", params={"month": "2026-10"}).json()
    from app.controllers.ingest import delete_all_data
    with SessionLocal() as db:
        b = get_business(CurrentUser(uid="google-wipe-user-1", name="Wipe Me", demo=False), db)
        out = delete_all_data(db, b, CurrentUser(uid="google-wipe-user-1", name="Wipe Me", demo=False))
        assert out["deleted"] is True and out["rows"]["purchase_invoices"] > 0
        assert analytics.available_months(db, b.id) == [] and b.gstin == ""
    assert client.get("/api/v1/dashboard/summary", params={"month": "2026-10"}).json() == before  # the demo owner is untouched
