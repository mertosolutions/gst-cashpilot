"""Fixture generator for earlier months. It writes the same file formats a user would upload
(purchase register csv, GSTR-2B xlsx, sales summary csv); the loader ingests them through the normal intake layer."""
from __future__ import annotations

import csv
import io
import random

from openpyxl import Workbook

BUYER = "27AAAAA0000A1Z5"
VENDORS = [
    ("27BBBBB1111B1Z6", "Sunrise Packaging Pvt Ltd", 0.04), ("27CCCCC2222C1Z7", "Metro Office Supplies", 0.05),
    ("27DDDDD3333D1Z8", "Kalyan Logistics", 0.34), ("27EEEEE4444E1Z9", "Shree Electricals", 0.06),
    ("27FFFFF5555F1Z0", "Mumbai Print House", 0.05), ("27GGGGG6666G1Z1", "Apex IT Services", 0.04),
    ("29HHHHH7777H1Z2", "Bangalore Components Ltd", 0.1), ("29IIIII8888I1Z3", "Deccan Steel Traders", 0.28),
    ("24JJJJJ9999J1Z4", "Gujarat Chemicals", 0.07), ("27KKKKK1010K1Z5", "Raj Stationers", 0.05),
    ("33LLLLL2020L1Z6", "Chennai Fasteners", 0.18), ("27MMMMM3030M1Z7", "City Auto Dealers", 0.02),
]
BLOCKED_CATEGORIES = ["Motor car (blocked credit)", "Food and beverages", "Club membership"]


def _tax(v: float, gstin: str, rate: float):
    t = round(v * rate, 2)
    return (0.0, round(t / 2, 2), round(t / 2, 2)) if gstin.startswith("27") else (t, 0.0, 0.0)


def generate_month(month: str, seed: int, growth: float = 1.0) -> dict[str, bytes]:
    rng = random.Random(seed)
    y, mo = int(month[:4]), int(month[5:])
    books, g2b = [], []
    n = int(rng.randint(40, 52) * growth)
    for i in range(1, n + 1):
        g, name, p_missing = rng.choice(VENDORS)
        blocked = g.endswith("3030M1Z7") or (rng.random() < 0.03)
        cat = rng.choice(BLOCKED_CATEGORIES) if blocked else "General purchase"
        v = float(rng.choice([4000, 6500, 8200, 12000, 15500, 21000, 27500, 34000, 42000, 56000]) * growth)
        igst, cgst, sgst = _tax(v, g, rng.choice([0.05, 0.12, 0.18]))
        day = rng.randint(1, 28)
        row = dict(no=f"INV/{i:03d}" if i % 2 else f"{name[:3].upper()}-{i:04d}", date=f"{y:04d}-{mo:02d}-{day:02d}", gstin=g, name=name,
                   taxable=v, igst=igst, cgst=cgst, sgst=sgst, category=cat)
        books.append(row)
        roll = rng.random()
        if roll < p_missing:
            continue  # supplier did not report it: missing in GSTR-2B
        d = dict(row)
        if roll > 0.93:  # amount mismatch: 2B shows less
            f = rng.choice([0.7, 0.8, 0.9])
            d["taxable"] = round(v * f, 2)
            d["igst"], d["cgst"], d["sgst"] = (round(x * f, 2) for x in (igst, cgst, sgst))
        if i % 7 == 0:
            d["no"] = d["no"].lower().replace("/", "-")
        g2b.append(d)
    for k in range(rng.randint(2, 4)):  # reported by suppliers but not in the books
        g, name, _ = rng.choice(VENDORS)
        v = float(rng.choice([6500, 12000, 21000]))
        igst, cgst, sgst = _tax(v, g, 0.18)
        g2b.append(dict(no=f"X{mo:02d}{900 + k}", date=f"{y:04d}-{mo:02d}-{rng.randint(1, 28):02d}", gstin=g, name=name,
                        taxable=v, igst=igst, cgst=cgst, sgst=sgst, category="General purchase"))
    rng.shuffle(g2b)

    reg = io.StringIO()
    w = csv.writer(reg)
    w.writerow(["invoice_no", "invoice_date", "supplier_gstin", "supplier_name", "taxable_value", "igst", "cgst", "sgst", "category"])
    for b in books:
        w.writerow([b["no"], b["date"], b["gstin"], b["name"], b["taxable"], b["igst"], b["cgst"], b["sgst"], b["category"]])

    wb = Workbook()
    ws0 = wb.active
    ws0.title = "Read me"
    ws0.append(["GSTR-2B (DUMMY generated fixture)"])
    ws0.append(["GSTIN of recipient", BUYER])
    ws = wb.create_sheet("B2B")
    ws.append(["GSTIN of supplier", "Trade/Legal name", "Invoice number", "Invoice type", "Invoice Date", "Invoice Value", "Place of supply", "Reverse Charge",
               "Taxable Value", "Integrated Tax", "Central Tax", "State/UT Tax", "Cess", "GSTR-1/IFF/GSTR-5 Period", "GSTR-1/IFF/GSTR-5 Filing Date", "ITC Availability", "Reason"])
    for d in g2b:
        ws.append([d["gstin"], d["name"], d["no"], "Regular", d["date"], round(d["taxable"] + d["igst"] + d["cgst"] + d["sgst"], 2), "27-Maharashtra", "No",
                   d["taxable"], d["igst"], d["cgst"], d["sgst"], 0, f"{mo:02d}{y}", f"{y:04d}-{mo:02d}-11", "Yes", ""])
    xb = io.BytesIO()
    wb.save(xb)

    tot = {"igst": 0.0, "cgst": 0.0, "sgst": 0.0}
    for b in books:
        for h in tot:
            tot[h] += b[h]
    sales = io.StringIO()
    sw = csv.writer(sales)
    sw.writerow(["month", "taxable_value", "igst", "cgst", "sgst"])
    k = 1.25 + rng.random() * 0.3
    sw.writerow([month, round(sum(b["taxable"] for b in books) * 1.6, 2), round(tot["igst"] * k + 18000, 2), round(tot["cgst"] * k + 45000, 2), round(tot["sgst"] * k + 45000, 2)])
    return {"register": reg.getvalue().encode(), "gstr2b": xb.getvalue(), "sales": sales.getvalue().encode()}
