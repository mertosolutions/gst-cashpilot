from datetime import date

from app.services.itc import blocked_tag, claim_deadline, filing_date
from app.services.tax import cash_payable
from app.services.util import clean_invoice_no, valid_gstin


def test_invoice_number_cleaning():
    assert clean_invoice_no("INV/001") == "INV1"
    assert clean_invoice_no("inv-0001") == "INV1"
    assert clean_invoice_no("X900") == "X900"  # zeros inside a number are kept
    assert clean_invoice_no("SUN-0003") == "SUN3"


def test_cash_payable_never_negative():
    assert cash_payable(450, 180) == 270
    assert cash_payable(100, 180) == 0


def test_gstin_format():
    assert valid_gstin("27AAAAA0000A1Z5")
    assert not valid_gstin("27AAAAA0000A1Z")
    assert not valid_gstin("")


def test_claim_time_limit():
    assert claim_deadline(date(2026, 10, 5)) == date(2027, 11, 30)  # FY 2026-27 ends Mar 2027
    assert claim_deadline(date(2026, 2, 5)) == date(2026, 11, 30)  # FY 2025-26
    assert filing_date("2026-10") == date(2026, 11, 20)


def test_blocked_category_keywords():
    assert blocked_tag("Motor car (blocked credit)") == "motor_vehicle"
    assert blocked_tag("General purchase") is None
