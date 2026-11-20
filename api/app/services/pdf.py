"""Draft PDF (GSTR-3B tables 3.1, 4 and 6) made with ReportLab."""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.util import HEADS, month_label


def _fmt(v: float) -> str:
    return f"{v:,.2f}"


def _table(rows, widths=None):
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f0fe")), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dadce0")),
                           ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
    return t


def draft_pdf(business_name: str, gstin: str, month: str, tables: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    st = getSampleStyleSheet()
    el = [Paragraph(f"GSTR-3B draft - {month_label(month)}", st["Title"]),
          Paragraph(f"{business_name} | GSTIN {gstin} | Amounts in Rs. DRAFT for review. Not filed.", st["Normal"]), Spacer(1, 12)]
    t31 = tables["table_3_1"]
    el += [Paragraph(t31["title"], st["Heading3"]),
           _table([["", "Taxable value", *[h.upper() for h in HEADS]], ["Outward taxable supplies", _fmt(t31["taxable_value"]), *[_fmt(t31["tax"][h]) for h in HEADS]]]), Spacer(1, 10)]
    t4 = tables["table_4"]
    el += [Paragraph(t4["title"], st["Heading3"]),
           _table([["", *[h.upper() for h in HEADS]], *[[r["label"], *[_fmt(r["tax"][h]) for h in HEADS]] for r in t4["rows"]]], [240, 80, 80, 80]), Spacer(1, 10)]
    t6 = tables["table_6"]
    rows = [["", "Head", "ITC claimed", "Cash payable"]]
    for c in t6["cases"]:
        for i, h in enumerate(HEADS):
            rows.append([c["label"] if i == 0 else "", h.upper(), _fmt(c["itc_claimed"][h]), _fmt(c["cash"][h])])
        rows.append(["", "Total", "", _fmt(c["total"])])
    el += [Paragraph(t6["title"], st["Heading3"]), _table(rows, [210, 60, 100, 100]), Spacer(1, 10),
           Paragraph(f"Cash saved by Case B: Rs. {_fmt(tables['summary']['cash_saved_by_case_b'])}. This is the ITC at risk. Case B is not confirmed by GSTR-2B.", st["Normal"])]
    doc.build(el)
    return buf.getvalue()
