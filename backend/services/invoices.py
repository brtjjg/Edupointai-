import os
import io
import base64
from datetime import datetime, timezone
import pytz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.colors import HexColor
import qrcode

# Brand Colors
NAVY = HexColor("#0A1C3A")
ROYAL_BLUE = HexColor("#2563EB")
GOLD = HexColor("#F59E0B")
LIGHT_GRAY = HexColor("#F3F4F6")
DARK_GRAY = HexColor("#4B5563")
GREEN = HexColor("#15803D")
LIGHT_GREEN = HexColor("#E8F8EF")

nairobi_tz = pytz.timezone('Africa/Nairobi')

_STATUS_DISPLAY = {
    "PENDING": "Awaiting Payment",
    "PAID": "Paid ✓",
    "COMPLETED": "Paid ✓",
    "FAILED": "Failed",
    "REVERSED": "Reversed",
    "INVALID": "Invalid",
}

def generate_invoice_pdf(user, payment):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=20*mm, leftMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)
    story = []

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(name="InvTitle", fontName="Helvetica-Bold", fontSize=28, textColor=NAVY, alignment=2))
    styles.add(ParagraphStyle(name="CompanyInfo", fontName="Helvetica", fontSize=9, leading=12, textColor=DARK_GRAY))
    styles.add(ParagraphStyle(name="SectionHeader", fontName="Helvetica-Bold", fontSize=11, textColor=ROYAL_BLUE, spaceAfter=5))
    styles.add(ParagraphStyle(name="InvBody", fontName="Helvetica", fontSize=10, leading=14, textColor=DARK_GRAY))
    styles.add(ParagraphStyle(name="TotalText", fontName="Helvetica-Bold", fontSize=14, textColor=NAVY, alignment=2))
    styles.add(ParagraphStyle(name="PayBtn", fontName="Helvetica-Bold", fontSize=15, textColor=colors.white, alignment=1))
    styles.add(ParagraphStyle(name="PayLink", fontName="Helvetica", fontSize=8, textColor=DARK_GRAY, alignment=1, leading=11))

    # Format dates safely
    created_at = payment.get("created_at")
    if created_at is None:
        created_at = datetime.now(nairobi_tz)
    elif isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except Exception:
            created_at = datetime.now(nairobi_tz)

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    created_at = created_at.astimezone(nairobi_tz)

    inv_date = created_at.strftime("%d %b %Y")
    inv_number = f"INV-{payment['transaction_id'][-8:].upper()}"
    status = str(payment.get("status", "pending")).upper()
    status_display = _STATUS_DISPLAY.get(status, status)

    is_paid = status in ("COMPLETED", "PAID")
    doc_title = "RECEIPT" if is_paid else "INVOICE"

    payment_link = (payment.get("redirect_url") or payment.get("payment_link") or "").strip()
    amount = float(payment.get("amount", 0))

    # ==========================================
    # 1. HEADER
    # ==========================================
    header_data = [[
        Paragraph("<b>🎓 EduPoint AI</b><br/><font size=8 color='#4B5563'>Your Education. Your Future.</font>", styles["Normal"]),
        Paragraph(
            f"<font size=24 color='#0A1C3A'><b>{doc_title}</b></font><br/>"
            f"<font size=10 color='#F59E0B'><b>{inv_number}</b></font>",
            styles["Normal"]
        )
    ]]
    header_table = Table(header_data, colWidths=[90*mm, 80*mm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 15),
        ('LINEBELOW', (0,0), (-1,-1), 2, NAVY),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10*mm))

    # ==========================================
    # 2. BILL TO & DETAILS
    # ==========================================
    billing_data = [
        [Paragraph("<b>BILL TO:</b>", styles["SectionHeader"]), Paragraph("<b>DETAILS:</b>", styles["SectionHeader"])],
        [
            Paragraph(f"<b>{user.get('name', 'Student')}</b><br/>{user.get('email')}<br/>ID: {user.get('id')}", styles["InvBody"]),
            Paragraph(
                f"<b>Date:</b> {inv_date}<br/>"
                f"<b>Status:</b> <font color='#F59E0B'>{status_display}</font><br/>"
                f"<b>Reference:</b> {payment['transaction_id']}",
                styles["InvBody"]
            )
        ]
    ]
    billing_table = Table(billing_data, colWidths=[85*mm, 85*mm])
    billing_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(billing_table)
    story.append(Spacer(1, 10*mm))

    # ==========================================
    # 3. SERVICE DESCRIPTION
    # ==========================================
    service_data = [
        [Paragraph("<b>DESCRIPTION</b>", styles["Normal"]), Paragraph("<b>AMOUNT</b>", styles["Normal"])],
        [
            Paragraph(
                "Academic Assessment & Course Matching<br/>"
                "<font size=8 color='#4B5563'>Includes cluster point calculation, comprehensive university matching (all 200+ courses), "
                "subject requirements for each course, and personalised PDF report via email.</font>",
                styles["InvBody"]
            ),
            Paragraph(f"KES {amount:,.2f}", styles["InvBody"])
        ]
    ]
    service_table = Table(service_data, colWidths=[130*mm, 40*mm])
    service_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), NAVY),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.lightgrey),
    ]))
    story.append(service_table)
    story.append(Spacer(1, 5*mm))

    # ==========================================
    # 4. FINANCIAL SUMMARY
    # ==========================================
    summary_data = [
        [Paragraph("Subtotal:", styles["InvBody"]), Paragraph(f"KES {amount:,.2f}", styles["InvBody"])],
        [Paragraph("Tax (0%):", styles["InvBody"]), Paragraph("KES 0.00", styles["InvBody"])],
        [Paragraph("<b>Total Amount Due:</b>", styles["TotalText"]), Paragraph(f"<b>KES {amount:,.2f}</b>", styles["TotalText"])],
        [Paragraph("<b>Amount Paid:</b>", styles["InvBody"]),
         Paragraph(f"KES {amount:,.2f}" if is_paid else "KES 0.00", styles["InvBody"])],
        [Paragraph("<b>Outstanding Balance:</b>", styles["InvBody"]),
         Paragraph("KES 0.00" if is_paid else f"KES {amount:,.2f}", styles["InvBody"])]
    ]
    summary_table = Table(summary_data, colWidths=[40*mm, 40*mm], hAlign='RIGHT')
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
        ('LINEABOVE', (0,2), (-1,2), 1, NAVY),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 12*mm))

    # ==========================================
    # 5. PAYMENT SECTION
    # ==========================================
    if is_paid:
        # -------- PAID / RECEIPT --------
        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(f"https://edupointai-frontend.vercel.app/verify?inv={inv_number}&tx={payment['transaction_id']}")
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)

        paid_block = [[
            RLImage(qr_buffer, width=28*mm, height=28*mm),
            Paragraph(
                "<b>✓ PAYMENT RECEIVED</b><br/>"
                "Thank you! Your payment has been confirmed.<br/>"
                "Your comprehensive Results Report has been sent to your email address.<br/><br/>"
                "<b>Support:</b> academichelpdesk1@gmail.com",
                styles["InvBody"]
            )
        ]]
        paid_table = Table(paid_block, colWidths=[35*mm, 135*mm])
        paid_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BACKGROUND', (0,0), (-1,-1), LIGHT_GREEN),
            ('BOX', (0,0), (-1,-1), 1.5, GREEN),
            ('TOPPADDING', (0,0), (-1,-1), 15),
            ('BOTTOMPADDING', (0,0), (-1,-1), 15),
            ('LEFTPADDING', (0,0), (-1,-1), 15),
        ]))
        story.append(paid_table)

    else:
        # -------- PENDING / PAY NOW --------
        story.append(Paragraph("<b>PAYMENT REQUIRED</b>", styles["SectionHeader"]))
        story.append(Spacer(1, 3*mm))

        if payment_link:
            # Big clickable PAY NOW button
            pay_button_data = [[
                Paragraph(
                    f'<a href="{payment_link}" color="white"><b>💳  PAY NOW  —  KES {amount:,.0f}</b></a>',
                    styles["PayBtn"]
                )
            ]]
            pay_button = Table(pay_button_data, colWidths=[170*mm], rowHeights=[14*mm])
            pay_button.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), ROYAL_BLUE),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ]))
            story.append(pay_button)
            story.append(Spacer(1, 3*mm))

            # Copy-paste link fallback
            story.append(Paragraph(
                f'<font size="8" color="#4B5563">Or copy this link into your browser:</font><br/>'
                f'<a href="{payment_link}"><font size="9" color="#2563EB">{payment_link}</font></a>',
                styles["PayLink"]
            ))
            story.append(Spacer(1, 6*mm))

        # QR + instructions
        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(payment_link or f"https://edupointai-frontend.vercel.app/verify?inv={inv_number}")
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)

        pending_block = [[
            RLImage(qr_buffer, width=28*mm, height=28*mm),
            Paragraph(
                "<b>SCAN TO PAY</b><br/>"
                "Scan the QR code to open the secure Pesapal checkout.<br/>"
                "Pay via M-PESA, Airtel Money, T-Kash, or Card.<br/><br/>"
                "Once paid you will be returned to the EduPointAI website, and your Results Report will be sent automatically to your email.<br/><br/>"
                "<b>Support:</b> academichelpdesk1@gmail.com",
                styles["InvBody"]
            )
        ]]
        pending_table = Table(pending_block, colWidths=[35*mm, 135*mm])
        pending_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BACKGROUND', (0,0), (-1,-1), LIGHT_GRAY),
            ('BOX', (0,0), (-1,-1), 1, ROYAL_BLUE),
            ('TOPPADDING', (0,0), (-1,-1), 15),
            ('BOTTOMPADDING', (0,0), (-1,-1), 15),
            ('LEFTPADDING', (0,0), (-1,-1), 15),
        ]))
        story.append(pending_table)

    doc.build(story)
    buffer.seek(0)
    return buffer
