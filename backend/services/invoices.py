import os
import io
import base64
import logging
from datetime import datetime, timezone
import pytz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, StyleSheet1
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.colors import HexColor
import qrcode

from brevo import Brevo
from brevo.transactional_emails import (
    SendTransacEmailRequestSender,
    SendTransacEmailRequestToItem,
    SendTransacEmailRequestAttachment,
)

logger = logging.getLogger(__name__)

# Brand Colors
NAVY = HexColor("#0A1C3A")
ROYAL_BLUE = HexColor("#2563EB")
GOLD = HexColor("#F59E0B")
LIGHT_GRAY = HexColor("#F3F4F6")
DARK_GRAY = HexColor("#4B5563")
GREEN = HexColor("#15803D")
LIGHT_GREEN = HexColor("#E8F8EF")
RED = HexColor("#DC2626")
LIGHT_RED = HexColor("#FEE2E2")

nairobi_tz = pytz.timezone('Africa/Nairobi')

PAID_STATUSES = {"PAID", "COMPLETED", "COMPLETE", "SUCCESS", "SUCCESSFUL"}
FAILED_STATUSES = {"FAILED", "REVERSED", "INVALID", "CANCELLED"}

_STATUS_DISPLAY = {
    "PENDING": "Awaiting Payment",
    "PAID": "Paid ✓",
    "COMPLETED": "Paid ✓",
    "FAILED": "Failed",
    "REVERSED": "Reversed",
    "INVALID": "Invalid",
}

def _safe_tx(payment):
    """Safely extract transaction ID to prevent slicing errors."""
    tx = payment.get("transaction_id")
    return str(tx) if tx else "UNKNOWN"


def generate_invoice_pdf(user, payment):
    """Generates the Invoice/Receipt PDF. Returns a BytesIO buffer."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=20*mm, leftMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)
    story = []

    # 🔑 FIX: Use StyleSheet1() instead of getSampleStyleSheet() to prevent memory leaks/crashes on 2nd run
    styles = StyleSheet1()
    styles.add(ParagraphStyle(name="InvTitle", fontName="Helvetica-Bold", fontSize=28, textColor=NAVY, alignment=2))
    styles.add(ParagraphStyle(name="CompanyInfo", fontName="Helvetica", fontSize=9, leading=12, textColor=DARK_GRAY))
    styles.add(ParagraphStyle(name="SectionHeader", fontName="Helvetica-Bold", fontSize=11, textColor=ROYAL_BLUE, spaceAfter=5))
    styles.add(ParagraphStyle(name="InvBody", fontName="Helvetica", fontSize=10, leading=14, textColor=DARK_GRAY))
    styles.add(ParagraphStyle(name="TotalText", fontName="Helvetica-Bold", fontSize=14, textColor=NAVY, alignment=2))
    styles.add(ParagraphStyle(name="PayBtn", fontName="Helvetica-Bold", fontSize=15, textColor=colors.white, alignment=1))
    styles.add(ParagraphStyle(name="PayLink", fontName="Helvetica", fontSize=8, textColor=DARK_GRAY, alignment=1, leading=11))
    styles.add(ParagraphStyle(name="Normal", fontName="Helvetica", fontSize=10, textColor=DARK_GRAY))

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
    tx = _safe_tx(payment)
    inv_number = f"INV-{tx[-8:].upper()}"
    status = str(payment.get("status", "PENDING")).upper()
    status_display = _STATUS_DISPLAY.get(status, status)

    is_paid = status in PAID_STATUSES
    is_failed = status in FAILED_STATUSES
    
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
    status_color = '#15803D' if is_paid else ('#DC2626' if is_failed else '#F59E0B')
    
    billing_data = [
        [Paragraph("<b>BILL TO:</b>", styles["SectionHeader"]), Paragraph("<b>DETAILS:</b>", styles["SectionHeader"])],
        [
            Paragraph(f"<b>{user.get('name', 'Student')}</b><br/>{user.get('email')}<br/>ID: {user.get('id')}", styles["InvBody"]),
            Paragraph(
                f"<b>Date:</b> {inv_date}<br/>"
                f"<b>Status:</b> <font color='{status_color}'>{status_display}</font><br/>"
                f"<b>Reference:</b> {tx}",
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
        qr.add_data(f"https://edupointai-frontend.vercel.app/verify?inv={inv_number}&tx={tx}")
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

    elif is_failed:
        # -------- FAILED --------
        failed_block = [[Paragraph(
            "<b>✗ PAYMENT NOT COMPLETED</b><br/>"
            "Your payment attempt was not successful.<br/>"
            "No charge was made to your account.<br/><br/>"
            "You can retry from the EduPoint AI dashboard or contact "
            "<b>academichelpdesk1@gmail.com</b> for help.",
            styles["InvBody"]
        )]]
        failed_table = Table(failed_block, colWidths=[170*mm])
        failed_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), LIGHT_RED),
            ('BOX', (0,0), (-1,-1), 1.5, RED),
            ('TOPPADDING', (0,0), (-1,-1), 15),
            ('BOTTOMPADDING', (0,0), (-1,-1), 15),
            ('LEFTPADDING', (0,0), (-1,-1), 15),
        ]))
        story.append(failed_table)

    else:
        # -------- PENDING / PAY NOW --------
        story.append(Paragraph("<b>PAYMENT REQUIRED</b>", styles["SectionHeader"]))
        story.append(Spacer(1, 3*mm))

        if payment_link:
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

            story.append(Paragraph(
                f'<font size="8" color="#4B5563">Or copy this link into your browser:</font><br/>'
                f'<a href="{payment_link}"><font size="9" color="#2563EB">{payment_link}</font></a>',
                styles["PayLink"]
            ))
            story.append(Spacer(1, 6*mm))

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


# ==========================================
# EMAIL SENDING FUNCTIONS
# ==========================================

def send_pending_invoice(user, payment):
    """Sends the 'Awaiting Payment' email with the Pay Now button and PDF (Matches Screenshot 1)."""
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("SENDER_EMAIL")
    
    if not api_key or not sender_email:
        logger.error("Brevo credentials missing (BREVO_API_KEY / SENDER_EMAIL).")
        return False

    if not user or not user.get("email"):
        logger.error(f"Cannot send invoice — user has no email: {user}")
        return False

    tx = _safe_tx(payment)
    inv_number = f"INV-{tx[-8:].upper()}"
    amount = float(payment.get("amount", 100))
    pay_link = payment.get("redirect_url", "#")

    try:
        # 1. Generate PDF
        pdf_buffer = generate_invoice_pdf(user, payment)
        pdf_b64 = base64.b64encode(pdf_buffer.getvalue()).decode("utf-8")

        # 2. Build HTML Body
        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
            <h2>Hi {user.get('name', 'Student')},</h2>
            <p>Thank you for using <b>EduPointAI</b>! Your invoice is attached below.</p>
            
            <div style="background-color: #F0F4F8; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 5px 0;"><b>Invoice:</b> {inv_number}</p>
                <p style="margin: 5px 0;"><b>Amount:</b> KES {amount:,.2f}</p>
                <p style="margin: 5px 0;"><b>Status:</b> Awaiting Payment</p>
            </div>

            <p>Complete the payment to unlock your <b>Comprehensive Results Report</b>: all 200+ courses, their subject requirements, cutoffs, and scholarship opportunities.</p>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{pay_link}" style="background-color: #2563EB; color: white; padding: 15px 30px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 16px; display: inline-block;">
                    💳 PAY NOW — KES {amount:,.0f}
                </a>
            </div>

            <p style="font-size: 12px; color: #666; text-align: center;">
                You will be redirected to Pesapal to pay via M-Pesa, Airtel Money, TKash, or Card.<br><br>
                Once paid you'll be returned to the EduPointAI website and your report will arrive by email.
            </p>
            
            <p style="margin-top: 30px;">Best regards,<br><b>EduPointAI Team</b></p>
        </div>
        """

        # 3. Send via Brevo
        client = Brevo(api_key=api_key)
        client.transactional_emails.send_transac_email(
            subject=f"EduPointAI Invoice {inv_number[-8:]} — KES {amount:,.0f}",
            html_content=html_content,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user['email'])],
            attachment=[
                SendTransacEmailRequestAttachment(
                    content=pdf_b64,
                    name=f"{inv_number}.pdf"
                )
            ]
        )
        logger.info(f"Pending invoice sent to {user['email']}")
        return True
    except Exception as e:
        logger.error(f"Failed to send pending invoice: {e}")
        return False


def send_success_email_with_receipt(user, payment, results_pdf_buffer):
    """Sends the Success email with BOTH Results PDF and Receipt PDF (Matches Screenshot 2)."""
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("SENDER_EMAIL")

    if not api_key or not sender_email:
        logger.error("Brevo credentials missing (BREVO_API_KEY / SENDER_EMAIL).")
        return False

    if not user or not user.get("email"):
        logger.error(f"Cannot send success email — user has no email: {user}")
        return False

    tx = _safe_tx(payment)
    inv_number = f"INV-{tx[-8:].upper()}"
    amount = float(payment.get("amount", 100))

    try:
        # 1. Generate Receipt PDF
        # Force status to PAID so it renders the receipt layout
        payment_copy = dict(payment)
        payment_copy['status'] = 'PAID' 
        receipt_buffer = generate_invoice_pdf(user, payment_copy)
        
        # 2. Encode both PDFs to Base64
        receipt_b64 = base64.b64encode(receipt_buffer.getvalue()).decode("utf-8")
        results_b64 = base64.b64encode(results_pdf_buffer.getvalue()).decode("utf-8")

        # 3. Build HTML Body
        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #333;">
            <h2>Payment successful! ✓</h2>
            <p>Hi {user.get('name', 'Student')},</p>
            <p>Thank you! Your payment of <b>KES {amount:,.2f}</b> has been confirmed.</p>
            <p>Your comprehensive Results Report and Receipt are attached to this email.</p>
            
            <p>You can also view your results anytime on your dashboard.</p>
            
            <p style="margin-top: 30px;">Best regards,<br><b>EduPointAI Team</b></p>
        </div>
        """

        # 4. Send via Brevo with BOTH attachments
        client = Brevo(api_key=api_key)
        client.transactional_emails.send_transac_email(
            subject="Your EduPointAI Results & Receipt",
            html_content=html_content,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user['email'])],
            attachment=[
                SendTransacEmailRequestAttachment(
                    content=results_b64,
                    name="EduPointAI_Results.pdf"
                ),
                SendTransacEmailRequestAttachment(
                    content=receipt_b64,
                    name=f"Receipt_{inv_number}.pdf"
                )
            ]
        )
        logger.info(f"Results & Receipt sent to {user['email']}")
        return True
    except Exception as e:
        logger.error(f"Failed to send success email: {e}")
        return False
