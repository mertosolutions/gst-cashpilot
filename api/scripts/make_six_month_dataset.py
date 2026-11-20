"""Builds one realistic six month dataset (May to Oct 2026) as the three files the app takes: purchase register, GSTR-2B and sales summary.
Volumes and amounts change from month to month (a quieter start, a busy festive October); sales are about 1.5x purchases so output tax is
larger than the credit, and about 80% of invoices match GSTR-2B, a few mismatch, some are missing, a few are only in 2B.
Run:  python scripts/make_six_month_dataset.py OUT_DIR"""
import csv, io, random, sys
from pathlib import Path
from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.seed.generator import generate_month, BUYER  # noqa: E402

PROFILE = [("2026-05", 0.80), ("2026-06", 0.90), ("2026-07", 1.05), ("2026-08", 0.95), ("2026-09", 1.20), ("2026-10", 1.45)]


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    reg_rows, b2b_rows, sales_rows, header_reg, header_b2b = [], [], [], None, None
    for i, (month, growth) in enumerate(PROFILE):
        f = generate_month(month, 4100 + i * 17, growth, series=f"{month[5:]}-")
        r = list(csv.reader(io.StringIO(f["register"].decode())))
        header_reg = r[0]; reg_rows += r[1:]
        ws = load_workbook(io.BytesIO(f["gstr2b"]))["B2B"]
        rows = [[c.value for c in row] for row in ws.iter_rows()]
        header_b2b = rows[0]; b2b_rows += rows[1:]
        # sales: about 1.5x the month's purchases (a trader's mark-up), taxed at a blended ~10%, mostly CGST + SGST
        rng = random.Random(900 + i)
        books = r[1:]
        purchase_taxable = sum(float(x[4].replace(",", "")) for x in books)
        sales_taxable = round(purchase_taxable * rng.uniform(1.40, 1.70) / 100) * 100
        tax_total = sales_taxable * rng.uniform(0.098, 0.108)
        igst = round(tax_total * rng.uniform(0.10, 0.18))
        half = round((tax_total - igst) / 2)
        sales_rows.append([month, sales_taxable, igst, half, half])
    with open(out / "purchase_register_may_oct2026.csv", "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\r\n"); w.writerow(header_reg); w.writerows(reg_rows)
    with open(out / "sales_summary_may_oct2026.csv", "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\r\n"); w.writerow(["month", "taxable_value", "igst", "cgst", "sgst"]); w.writerows(sales_rows)
    wb = Workbook(); ws0 = wb.active; ws0.title = "Read me"
    ws0.append(["GSTR-2B (DUMMY generated data)"]); ws0.append(["GSTIN of recipient", BUYER])
    ws = wb.create_sheet("B2B"); ws.append(header_b2b)
    for row in b2b_rows:
        ws.append(row)
    wb.save(out / "GSTR-2B_may_oct2026_dummy.xlsx")
    print(f"register {len(reg_rows)} rows, gstr2b {len(b2b_rows)} rows, sales {len(sales_rows)} rows")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
