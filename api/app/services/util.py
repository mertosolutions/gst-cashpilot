import json
import re
from datetime import date, datetime
from functools import lru_cache

from app.core.config import BASE_DIR

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
HEADS = ("igst", "cgst", "sgst")


def money(x) -> float:
    return round(float(x or 0), 2)


def clean_invoice_no(raw: str) -> str:
    """INV/001 and inv-0001 both become INV1: upper case, drop symbols, drop leading zeros of every number."""
    s = re.sub(r"[^A-Z0-9]", "", str(raw or "").upper())
    return re.sub(r"(?<![0-9])0+(?=[0-9])", "", s)


def valid_gstin(g: str) -> bool:
    return bool(GSTIN_RE.match((g or "").strip().upper()))


def month_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def parse_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%d-%b-%Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date: {v!r}")


def prev_month(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:])
    mo -= 1
    if mo == 0:
        y, mo = y - 1, 12
    return f"{y:04d}-{mo:02d}"


def next_month(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:])
    mo += 1
    if mo == 13:
        y, mo = y + 1, 1
    return f"{y:04d}-{mo:02d}"


def month_label(m: str) -> str:
    return datetime.strptime(m + "-01", "%Y-%m-%d").strftime("%b %Y")


@lru_cache
def rules_config() -> dict:
    return json.loads((BASE_DIR / "app/data/rules/config.json").read_text())


@lru_cache
def rules_passages() -> list[dict]:
    return json.loads((BASE_DIR / "app/data/rules/passages.json").read_text())["passages"]
