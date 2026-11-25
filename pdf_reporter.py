import os
from datetime import datetime
from typing import Any, Dict, List
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_daily_bookings_pdf(
    business: Dict[str, Any],
    date_str: str,
    bookings: List[Dict[str, Any]],
    output_dir: str = "/tmp/booking_reports",
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    safe_biz = "".join(ch if ch.isalnum() else "_" for ch in str(business.get("_id", "biz")))
    filename = f"bookings_{safe_biz}_{date_str}.pdf"
    filepath = os.path.join(output_dir, filename)

    doc = SimpleDocTemplate(filepath, pagesize=A4, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    elements = []

    biz_name = business.get("business_name", "Business")
    elements.append(Paragraph(f"<b>{biz_name} — Daily Bookings Report</b>", styles["Title"]))
    elements.append(
        Paragraph(
            f"Date: <b>{date_str}</b> &nbsp;|&nbsp; Total Confirmed Bookings: <b>{len(bookings)}</b>",
            styles["Normal"],
        )
    )
    elements.append(Spacer(1, 14))

    if not bookings:
        elements.append(Paragraph("No confirmed bookings scheduled for this date.", styles["Normal"]))
    else:
        table_data = [["Time", "Customer Name", "Phone", "Booking Details"]]
        for b in bookings:
            details_val = b.get("details") or "—"
            table_data.append(
                [
                    str(b.get("time", "")),
                    str(b.get("customer_name", "—")),
                    str(b.get("customer_phone", "—")),
                    Paragraph(str(details_val), styles["BodyText"]),
                ]
            )

        table = Table(table_data, colWidths=[65, 135, 115, 200], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elements.append(table)

    elements.append(Spacer(1, 16))
    elements.append(
        Paragraph(
            f"Generated at {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            styles["Normal"],
        )
    )

    doc.build(elements)
    return filepath