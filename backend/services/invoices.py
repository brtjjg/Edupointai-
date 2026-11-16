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
import logging

# Brevo v4 Imports
from brevo import Brevo
from brevo.transactional_emails import (
    SendTransacEmailRequestSender,
    SendTransacEmailRequestToItem,
    SendTransacEmailRequestAttachmentItem,
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

nairobi_tz = pytz.timezone('Africa/Nairobi')

_STATUS_DISPLAY = {
    "PENDING": "Awaiting Payment",
    "PAID": "Paid ✓",
    "COMPLETED": "Paid ✓",
    "FAILED": "Failed",
    "REVERSED": "Reversed",
    "INVALID": "Invalid",
}

# ==========================================
# HTML EMAIL TEMPLATE BUILDER
# ==========================================
def _build_email_html(status_type, title, subtitle, invoice_number, amount, button_text, button_link, extra_html=""):
    """Helper to build the exact card layout from the screenshots."""
    
    if status_type == "PENDING":
        pill_bg = "#f59e0b" # Amber
        pill_text = "AWAITING PAYMENT"
    elif status_type == "FAILED":
        pill_bg = "#ef4444" # Red
        pill_text = "PAYMENT FAILED"
    elif status_type == "REMINDER":
        pill_bg = "#f59e0b" # Amber
        pill_text = "PAYMENT REMINDER"
    else:
        pill_bg = "#10b981" # Green
        pill_text = "PAYMENT CONFIRMATION"
        
    title_color = "#0b1530"

    return f"""
    <div style="background-color: #f4f6f8; padding: 30px 15px; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05);">
            
            <!-- Header -->
            <div style="background-color: #0b1530; padding: 25px; text-align: center;">
                <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0.5px;">EduPointAI ✦</h1>
            </div>
            
            <!-- Body -->
            <div style="padding: 40px 30px; text-align: center;">
                <div style="background-color: {pill_bg}; color: #ffffff; padding: 6px 16px; border-radius: 20px; font-size: 11px; font-weight: bold; text-transform: uppercase; display: inline-block; margin-bottom: 25px; letter-spacing: 0.5px;">
                    {pill_text}
                </div>
                
                <h2 style="color: {title_color}; margin: 0 0 10px 0; font-size: 26px;">{title}</h2>
                <p style="color: #64748b; font-size: 15px; margin: 0 0 30px 0;">{subtitle}</p>
                
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
                
                <p style="color: #7952c7; font-size: 14px; font-weight: bold; margin: 0 0 10px 0; letter-spacing: 0.5px;">INVOICE {invoice_number}</p>
                <h1 style="color: #0b1530; font-size: 36px; margin: 0 0 25px 0; font-weight: 800;">KES {amount:,.2f}</h1>
                
                {extra_html}
                
                <a href="{button_link}" style="background-color: #7952c7; color: #ffffff; text-decoration: none; padding: 16px 40px; border-radius: 8px; font-weight: bold; font-size: 16px; display: inline-block; margin-bottom: 25px;">
                    {button_text}
                </a>
                
                <p style="color: #64748b; font-size: 13px; margin: 0;">You will be redirected to Pesapal to pay via M-Pesa, Airtel Money, T-Kash, or Card.</p>
            </div>
            
            <!-- Footer -->
            <div style="background-color: #f8fafc; padding: 20px; text-align: center; border-top: 1px solid #e2e8f0;">
                <p style="color: #64748b; font-size: 13px; margin: 0 0 5px 0;">Need help? Contact us at <a href="mailto:academichelpdesk1@gmail.com" style="color: #7952c7; text-decoration: none;">academichelpdesk1@gmail.com</a></p>
                <p style="color: #94a3b8; font-size: 12px; margin: 0;">© 2026 EduPointAI. All rights reserved.</p>
            </div>
        </div>
    </div>
    """

# ==========================================
# PDF GENERATION
# ==========================================
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

    if is_paid:
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

def _send_invoice_email(user, payment, payment_link, status_type, title, subtitle, subject):
    """Base function to send all invoice-related emails."""
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("SENDER_EMAIL")
    if not api_key or not sender_email:
        logger.error("Missing Brevo credentials")
        return False

    amount = float(payment.get("amount", 100))
    inv_number = f"INV-{payment['transaction_id'][-8:].upper()}"
    
    html_content = _build_email_html(
        status_type=status_type,
        title=title,
        subtitle=subtitle,
        invoice_number=inv_number,
        amount=amount,
        button_text=f"PAY NOW - KES {amount:,.0f}" if status_type in ["PENDING", "REMINDER", "FAILED"] else "VIEW MY REPORT",
        button_link=payment_link
    )

    try:
        client = Brevo(api_key=api_key)
        client.transactional_emails.send_transac_email(
            subject=subject,
            html_content=html_content,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user['email'])],
            attachment=[
                SendTransacEmailRequestAttachmentItem(
                    content=base64.b64encode(generate_invoice_pdf(user, payment).getvalue()).decode('utf-8'), 
                    name=f"Invoice_{inv_number}.pdf"
                )
            ]
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send {status_type} email: {e}")
        return False


def send_pending_invoice_email(user, payment, payment_link):
    inv_no = payment['transaction_id'][-8:].upper()
    return _send_invoice_email(
        user, payment, payment_link, 
        status_type="PENDING",
        title="Your invoice is ready!",
        subtitle="One step closer to unlocking your academic opportunities.",
        subject=f"EduPointAI Invoice {inv_no} — KES 100"
    )


def send_failed_invoice_email(user, payment, payment_link):
    inv_no = payment['transaction_id'][-8:].upper()
    return _send_invoice_email(
        user, payment, payment_link, 
        status_type="FAILED",
        title="Payment Failed",
        subtitle="Your recent transaction could not be completed. Please try again.",
        subject=f"Action Required: Payment Failed for Invoice {inv_no}"
    )


def send_invoice_reminder_email(user, payment, payment_link):
    inv_no = payment['transaction_id'][-8:].upper()
    return _send_invoice_email(
        user, payment, payment_link, 
        status_type="REMINDER",
        title="Reminder: Invoice Pending",
        subtitle="Just a friendly reminder to complete your payment to unlock your report.",
        subject=f"Reminder: Your EduPointAI Invoice {inv_no} is awaiting payment"
    )


def send_success_email_with_receipt(user, payment, results_pdf_buffer, cluster_points=None):
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("SENDER_EMAIL")
    if not api_key or not sender_email:
        logger.error("Missing Brevo credentials")
        return False

    invoice_buffer = generate_invoice_pdf(user, payment)
    inv_number = f"INV-{payment['transaction_id'][-8:].upper()}"
    
    def to_b64(buf):
        return base64.b64encode(buf.getvalue()).decode('utf-8')

    invoice_b64 = to_b64(invoice_buffer)
    results_b64 = to_b64(results_pdf_buffer)

    cluster_html = f'<p style="color: #0b1530; font-size: 16px; font-weight: bold; margin: 0 0 25px 0;">Cluster Points: {cluster_points}</p>' if cluster_points else ""
    
    html_content = f"""
    <div style="background-color: #f4f6f8; padding: 30px 15px; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05);">
            <div style="background-color: #0b1530; padding: 25px; text-align: center;">
                <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0.5px;">EduPointAI ✦</h1>
            </div>
            <div style="padding: 40px 30px; text-align: center;">
                <div style="background-color: #10b981; color: #ffffff; padding: 6px 16px; border-radius: 20px; font-size: 11px; font-weight: bold; text-transform: uppercase; display: inline-block; margin-bottom: 25px; letter-spacing: 0.5px;">
                    PAYMENT CONFIRMATION
                </div>
                <h2 style="color: #0b1530; margin: 0 0 15px 0; font-size: 26px;">Payment successful! ✔️</h2>
                <p style="color: #334155; font-size: 15px; margin: 0 0 30px 0;">Thank you! Your payment has been confirmed.</p>
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
                <h3 style="color: #7952c7; font-size: 20px; margin: 0 0 10px 0;">Your report is ready! 🎓</h3>
                <p style="color: #334155; font-size: 15px; margin: 0 0 10px 0;">Your next academic chapter starts here.</p>
                {cluster_html}
                <a href="https://edupointai-frontend.vercel.app" style="background-color: #7952c7; color: #ffffff; text-decoration: none; padding: 16px 40px; border-radius: 8px; font-weight: bold; font-size: 16px; display: inline-block; margin-bottom: 25px;">
                    VIEW MY REPORT
                </a>
                <p style="color: #64748b; font-size: 13px; margin: 0;">Your official Results Report and Payment Receipt are attached to this email.</p>
            </div>
            <div style="background-color: #f8fafc; padding: 20px; text-align: center; border-top: 1px solid #e2e8f0;">
                <p style="color: #64748b; font-size: 13px; margin: 0 0 5px 0;">Need help? Contact us at <a href="mailto:academichelpdesk1@gmail.com" style="color: #7952c7; text-decoration: none;">academichelpdesk1@gmail.com</a></p>
                <p style="color: #94a3b8; font-size: 12px; margin: 0;">© 2026 EduPointAI. All rights reserved.</p>
            </div>
        </div>
    </div>
    """

    try:
        client = Brevo(api_key=api_key)
        client.transactional_emails.send_transac_email(
            subject="Your EduPointAI Results & Receipt",
            html_content=html_content,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=user['email'])],
            attachment=[
                SendTransacEmailRequestAttachmentItem(content=results_b64, name="EduPointAI_Results.pdf"),
                SendTransacEmailRequestAttachmentItem(content=invoice_b64, name=f"Receipt_{inv_number}.pdf"),
            ]
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send receipt email: {e}")
        return False
