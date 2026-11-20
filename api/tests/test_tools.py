"""The ADK tools must read the business from the session state, never from model-provided arguments."""
from types import SimpleNamespace


def _ctx(client):
    from app.core.database import SessionLocal
    from app.models import Business
    with SessionLocal() as db:
        biz = db.query(Business).filter_by(owner_uid="demo-owner").first()
    return SimpleNamespace(state={"business_id": biz.id, "month": "2026-10"})


def test_tools_use_session_scope(client):
    from app.agents import tools
    ctx = _ctx(client)
    cash = tools.calculate_cash("2026-10", ctx)
    assert cash["cash_a"] > cash["cash_b"] > 0
    v = tools.vendor_summary("2026-10", 3, ctx)
    assert len(v["vendors"]) == 3 and v["vendors"][0]["at_risk"] >= v["vendors"][1]["at_risk"]
    rules = tools.search_rules("blocked credit motor car", ctx)
    assert "17(5)" in rules[0]["citation"]
    assert tools.get_decision("NOPE-1", "2026-10", ctx)["error"]


def test_tools_cannot_see_another_business(client):
    from app.agents import tools
    other = SimpleNamespace(state={"business_id": "not-a-real-business", "month": "2026-10"})
    assert tools.calculate_cash("2026-10", other)["cash_a"] == 0
    assert tools.vendor_summary("2026-10", 5, other)["vendors"] == []
