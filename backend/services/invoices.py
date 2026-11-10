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

nairobi_tz = pytz.timezone('Africa/Nairobi')

def generate_invoice_pdf(user, payment):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    story = []

    styles = getSampleStyleSheet()
    
    # Custom Styles (Using unique names to prevent ReportLab crashes)
    styles.add(ParagraphStyle(name="InvTitle", fontName="Helvetica-Bold", fontSize=28, textColor=NAVY, alignment=2))
    styles.add(ParagraphStyle(name="CompanyInfo", fontName="Helvetica", fontSize=9, leading=12, textColor=DARK_GRAY))
    styles.add(ParagraphStyle(name="SectionHeader", fontName="Helvetica-Bold", fontSize=11, textColor=ROYAL_BLUE, spaceAfter=5))
    styles.add(ParagraphStyle(name="InvBody", fontName="Helvetica", fontSize=10, leading=14, textColor=DARK_GRAY))
    styles.add(ParagraphStyle(name="TotalText", fontName="Helvetica-Bold", fontSize=14, textColor=NAVY, alignment=2))
    styles.add(ParagraphStyle(name="StatusText", fontName="Helvetica-Bold", fontSize=12, textColor=GOLD, alignment=2))

    # Format Dates Safely
    created_at = payment.get("created_at")
    if created_at is None:
        created_at = datetime.now(nairobi_tz)
    elif isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except:
            created_at = datetime.now(nairobi_tz)

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
        
    created_at = created_at.astimezone(nairobi_tz)
    
    inv_date = created_at.strftime("%d %b %Y")
    inv_number = f"INV-{payment['transaction_id'][-8:].upper()}"
    status = str(payment.get("status", "pending")).upper()

    # ==========================================
    # 1. COMPANY HEADER
    # ==========================================
    header_data = [
        [
            Paragraph("<b>🎓 EduPoint AI</b><br/><font size=8 color='#4B5563'>Your Education. Your Future.</font>", styles["Normal"]),
            Paragraph(f"<font size=24 color='#0A1C3A'><b>INVOICE</b></font><br/><font size=10 color='#F59E0B'><b>{inv_number}</b></font>", styles["Normal"])
        ]
    ]
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
    # 2. BILL TO & INVOICE DETAILS
    # ==========================================
    billing_data = [
        [Paragraph("<b>BILL TO:</b>", styles["SectionHeader"]), Paragraph("<b>INVOICE DETAILS:</b>", styles["SectionHeader"])],
        [Paragraph(f"<b>{user.get('name', 'Student')}</b><br/>{user.get('email')}<br/>ID: {user.get('id')}", styles["InvBody"]),
         Paragraph(f"<b>Date:</b> {inv_date}<br/><b>Status:</b> <font color='#F59E0B'>{status}</font><br/><b>Reference:</b> {payment['transaction_id']}", styles["InvBody"])]
    ]
    billing_table = Table(billing_data, colWidths=[85*mm, 85*mm])
    billing_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(billing_table)
    story.append(Spacer(1, 10*mm))

    # ==========================================
    # 3. SERVICE DESCRIPTION TABLE
    # ==========================================
    table_data = [
        [Paragraph("<b>DESCRIPTION</b>", styles["Normal"]), Paragraph("<b>AMOUNT</b>", styles["Normal"])],
        [Paragraph("Academic Assessment & Course Matching<br/><font size=8 color='#4B5563'>Includes cluster point calculation, university matching, and personalized digital report generation.</font>", styles["InvBody"]), 
         Paragraph(f"KES {float(payment['amount']):,.2f}", styles["InvBody"])]
    ]
    service_table = Table(table_data, colWidths=[130*mm, 40*mm])
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
        [Paragraph("Subtotal:", styles["InvBody"]), Paragraph(f"KES {float(payment['amount']):,.2f}", styles["InvBody"])],
        [Paragraph("Tax (0%):", styles["InvBody"]), Paragraph("KES 0.00", styles["InvBody"])],
        [Paragraph("<b>Total Amount Due:</b>", styles["TotalText"]), Paragraph(f"<b>KES {float(payment['amount']):,.2f}</b>", styles["TotalText"])],
        [Paragraph("<b>Amount Paid:</b>", styles["InvBody"]), Paragraph(f"KES {float(payment['amount']):,.2f}" if status == "COMPLETED" or status == "PAID" else "KES 0.00", styles["InvBody"])],
        [Paragraph("<b>Outstanding Balance:</b>", styles["InvBody"]), Paragraph("KES 0.00" if status == "COMPLETED" or status == "PAID" else f"KES {float(payment['amount']):,.2f}", styles["InvBody"])]
    ]
    summary_table = Table(summary_data, colWidths=[40*mm, 40*mm], hAlign='RIGHT')
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
        ('LINEABOVE', (0,2), (-1,2), 1, NAVY),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 15*mm))

    # ==========================================
    # 5. PAYMENT INSTRUCTIONS & QR
    # ==========================================
    qr = qrcode.QRCode(version=1, box_size=4, border=1)
    qr.add_data(f"https://edupointai-frontend.vercel.app/verify?inv={inv_number}&tx={payment['transaction_id']}")
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_buffer = io.BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    qr_image = RLImage(qr_buffer, width=25*mm, height=25*mm)

    footer_data = [
        [qr_image, 
         Paragraph("<b>PAYMENT INSTRUCTIONS</b><br/>Payments are processed securely via Pesapal.<br/>M-PESA, Airtel Money, T-Kash, or Card.<br/><br/><b>Support:</b> academichelpdesk1@gmail.com", styles["InvBody"])]
    ]
    footer_table = Table(footer_data, colWidths=[30*mm, 140*mm])
    footer_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,0), (-1,-1), LIGHT_GRAY),
        ('BOX', (0,0), (-1,-1), 1, ROYAL_BLUE),
        ('TOPPADDING', (0,0), (-1,-1), 15),
        ('BOTTOMPADDING', (0,0), (-1,-1), 15),
        ('LEFTPADDING', (0,0), (-1,-1), 15),
    ]))
    story.append(footer_table)

    # Build
    doc.build(story)
    buffer.seek(0)
    return buffer
