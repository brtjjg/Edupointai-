import os
import base64
import logging
from brevo import Brevo
from brevo.transactional_emails import SendTransacEmailRequestSender, SendTransacEmailRequestToItem
from services.invoices import generate_invoice_pdf

logger = logging.getLogger(__name__)

def _get_brevo():
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("SENDER_EMAIL")
    if not api_key or not sender_email:
        logger.warning("Brevo credentials missing. Email not sent.")
        return None, None
    return Brevo(api_key=api_key), sender_email

def _build_html_template(pill_text, pill_bg, title, body_html, button_text="", button_link="", extra_html=""):
    """The master layout for all EduPointAI emails."""
    button_block = ""
    if button_text and button_link:
        button_block = f"""
        <tr>
            <td align="center" style="padding-bottom: 30px;">
                <a href="{button_link}" target="_blank" style="display: inline-block; background: linear-gradient(90deg, #7047EB 0%, #5a35d6 100%); color: #ffffff; text-decoration: none; font-size: 16px; font-weight: 700; padding: 16px 40px; border-radius: 8px; box-shadow: 0 4px 12px rgba(112, 71, 235, 0.3);">{button_text}</a>
            </td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
    <body style="margin: 0; padding: 0; background-color: #F3F5FC; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #F3F5FC; padding: 40px 20px;">
            <tr>
                <td align="center">
                    <table width="100%" max-width="600" border="0" cellspacing="0" cellpadding="0" style="background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(16, 27, 61, 0.08);">
                        <tr>
                            <td style="background-color: #101B3D; padding: 30px 40px; text-align: center; border-bottom: 4px solid #7047EB;">
                                <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 0.5px;">EduPointAI ✦</h1>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 40px;">
                                <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                    <tr>
                                        <td align="center" style="padding-bottom: 20px;">
                                            <span style="display: inline-block; background-color: {pill_bg}; color: #ffffff; font-size: 11px; font-weight: 800; letter-spacing: 1.5px; padding: 6px 14px; border-radius: 20px; text-transform: uppercase;">{pill_text}</span>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td align="center" style="padding-bottom: 20px;">
                                            <h2 style="color: #26324D; margin: 0; font-size: 26px; font-weight: 700;">{title}</h2>
                                        </td>
                                    </tr>
                                    {body_html}
                                    {button_block}
                                    {extra_html}
                                </table>
                            </td>
                        </tr>
                        <tr>
                            <td style="background-color: #F8FAFC; padding: 30px 40px; text-align: center; border-top: 1px solid #E2E8F0;">
                                <p style="color: #64748B; margin: 0 0 15px 0; font-size: 13px; line-height: 1.5;">Need assistance? Contact us at <a href="mailto:nexoraacademyhelpdesk@gmail.com" style="color: #7047EB; text-decoration: none; font-weight: 600;">nexoraacademyhelpdesk@gmail.com</a></p>
                                <p style="color: #94A3B8; margin: 0; font-size: 12px;">EduPointAI ✦ Your Education. Your Future.</p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

def _send_email(to_email, to_name, subject, html_content, attachments=None):
    client, sender_email = _get_brevo()
    if not client: return False
    try:
        client.transactional_emails.send_transac_email(
            subject=subject,
            html_content=html_content,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPointAI"),
            to=[SendTransacEmailRequestToItem(email=to_email, name=to_name)],
            attachment=attachments or []
        )
        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False

# ==========================================
# MESSAGE TEMPLATES
# ==========================================

def send_msg_invoice_generated(user, payment):
    inv_short = payment['transaction_id'][-8:].upper()
    amount = float(payment['amount'])
    pay_link = payment.get('redirect_url', '')
    
    inv_pdf = generate_invoice_pdf(user, payment)
    attachments = [{"content": base64.b64encode(inv_pdf.getvalue()).decode('utf-8'), "name": f"Invoice_{inv_short}.pdf"}]

    body = f"""
    <tr><td align="center" style="padding-bottom: 30px;">
        <p style="color: #26324D; font-size: 16px; line-height: 1.6;">Hello <strong>{user['name']}</strong>,<br><br>Your EduPointAI invoice is ready! Thank you for choosing us to support your academic journey.</p>
        <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 20px; text-align: left; width: 80%; margin: 0 auto;">
            <p style="margin: 0 0 10px 0; font-size: 14px; color: #26324D;"><strong>INVOICE DETAILS</strong></p>
            <p style="margin: 0 0 5px 0; font-size: 14px; color: #64748B;">Invoice: INV-{inv_short}</p>
            <p style="margin: 0 0 5px 0; font-size: 14px; color: #64748B;">Amount: KES {amount:,.2f}</p>
            <p style="margin: 0; font-size: 14px; color: #64748B;">Status: Awaiting Payment</p>
        </div>
    </td></tr>
    """
    
    html = _build_html_template("Orange · Pending", "#F2A93B", "Your invoice is ready!", body, f"PAY NOW – KES {amount:,.0f}", pay_link,
        '<tr><td align="center"><p style="color: #64748B; font-size: 13px;">Your official invoice is attached to this email.</p></td></tr>')
    
    return _send_email(user['email'], user['name'], f"EduPointAI Invoice {inv_short} — KES {amount:.0f}", html, attachments)

def send_msg_payment_reminder(user, payment, hours_unpaid):
    inv_short = payment['transaction_id'][-8:].upper()
    amount = float(payment['amount'])
    pay_link = payment.get('redirect_url', '')
    
    inv_pdf = generate_invoice_pdf(user, payment)
    attachments = [{"content": base64.b64encode(inv_pdf.getvalue()).decode('utf-8'), "name": f"Invoice_{inv_short}.pdf"}]

    body = f"""
    <tr><td align="center" style="padding-bottom: 30px;">
        <p style="color: #26324D; font-size: 16px; line-height: 1.6;">Hello <strong>{user['name']}</strong>,<br><br>We noticed that your EduPointAI invoice is still awaiting payment. We don't want you to miss out on the academic guidance you requested.</p>
        <div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 20px; text-align: left; width: 80%; margin: 0 auto;">
            <p style="margin: 0 0 10px 0; font-size: 14px; color: #26324D;"><strong>YOUR OUTSTANDING INVOICE</strong></p>
            <p style="margin: 0 0 5px 0; font-size: 14px; color: #64748B;">Invoice: INV-{inv_short}</p>
            <p style="margin: 0 0 5px 0; font-size: 14px; color: #64748B;">Amount: KES {amount:,.2f}</p>
            <p style="margin: 0; font-size: 14px; color: #64748B;">Status: Pending</p>
        </div>
    </td></tr>
    """
    
    html = _build_html_template(f"Reminder · {hours_unpaid}hrs Unpaid", "#F2A93B", "Your invoice is still waiting", body, "COMPLETE PAYMENT", pay_link,
        '<tr><td align="center"><p style="color: #64748B; font-size: 13px;">If you have already paid, please disregard this reminder.</p></td></tr>')
    
    return _send_email(user['email'], user['name'], f"Reminder: Invoice INV-{inv_short} is unpaid", html, attachments)

def send_msg_payment_failed(user, payment):
    inv_short = payment['transaction_id'][-8:].upper()
    amount = float(payment['amount'])
    pay_link = payment.get('redirect_url', '')
    
    body = f"""
    <tr><td align="center" style="padding-bottom: 30px;">
        <p style="color: #26324D; font-size: 16px; line-height: 1.6;">Hello <strong>{user['name']}</strong>,<br><br>Unfortunately, we could not confirm your recent payment. Don't worry! You can try again.</p>
        <div style="background-color: #FEF2F2; border: 1px solid #FCA5A5; border-radius: 8px; padding: 20px; text-align: left; width: 80%; margin: 0 auto;">
            <p style="margin: 0 0 10px 0; font-size: 14px; color: #991B1B;"><strong>TRANSACTION DETAILS</strong></p>
            <p style="margin: 0 0 5px 0; font-size: 14px; color: #64748B;">Invoice: INV-{inv_short}</p>
            <p style="margin: 0 0 5px 0; font-size: 14px; color: #64748B;">Amount: KES {amount:,.2f}</p>
            <p style="margin: 0 0 5px 0; font-size: 14px; color: #64748B;">Transaction Ref: {payment['transaction_id']}</p>
            <p style="margin: 0; font-size: 14px; color: #991B1B;"><strong>Status: Failed</strong></p>
        </div>
        <p style="text-align: left; color: #64748B; font-size: 13px; margin-top: 15px;"><strong>What to do next:</strong><br>1. Check your payment details.<br>2. Ensure your payment method has sufficient funds.<br>3. Try again.</p>
    </td></tr>
    """
    
    html = _build_html_template("Red · Failed", "#EF4444", "Payment Failed", body, "RETRY PAYMENT", pay_link,
        '<tr><td align="center"><p style="color: #64748B; font-size: 13px;">If money was deducted, please contact support before retrying.</p></td></tr>')
    
    return _send_email(user['email'], user['name'], f"Action Required: Payment Failed for INV-{inv_short}", html)

def send_msg_payment_successful(user, payment):
    inv_short = payment['transaction_id'][-8:].upper()
    amount = float(payment['amount'])
    
    inv_pdf = generate_invoice_pdf(user, payment)
    attachments = [{"content": base64.b64encode(inv_pdf.getvalue()).decode('utf-8'), "name": f"Receipt_{inv_short}.pdf"}]

    body = f"""
    <tr><td align="center" style="padding-bottom: 30px;">
        <p style="color: #26324D; font-size: 16px; line-height: 1.6;">Hello <strong>{user['name']}</strong>,<br><br>Great news! Your payment has been successfully received by EduPointAI.</p>
        <div style="background-color: #ECFDF5; border: 1px solid #6EE7B7; border-radius: 8px; padding: 20px; text-align: left; width: 80%; margin: 0 auto;">
            <p style="margin: 0 0 10px 0; font-size: 14px; color: #065F46;"><strong>PAYMENT CONFIRMATION</strong></p>
            <p style="margin: 0 0 5px 0; font-size: 14px; color: #64748B;">Invoice: INV-{inv_short}</p>
            <p style="margin: 0 0 5px 0; font-size: 14px; color: #64748B;">Amount: KES {amount:,.2f}</p>
            <p style="margin: 0; font-size: 14px; color: #065F46;"><strong>Status: SUCCESSFUL</strong></p>
        </div>
        <p style="color: #64748B; font-size: 14px; margin-top: 15px;">Your request will now proceed to the next processing stage. We will notify you when your academic report is ready.</p>
    </td></tr>
    """
    
    html = _build_html_template("Green · Successful", "#0F9D91", "Payment Successful! ✓", body, "", "", "")
    return _send_email(user['email'], user['name'], "Payment Confirmation & Receipt", html, attachments)

def send_msg_report_processing(user):
    body = f"""
    <tr><td align="center" style="padding-bottom: 30px;">
        <p style="color: #26324D; font-size: 16px; line-height: 1.6;">Hello <strong>{user['name']}</strong>,<br><br>Thank you for completing your payment. We have successfully received your request, and your academic calculation is currently being processed.</p>
        <div style="background-color: #F1F5F9; border: 1px solid #CBD5E1; border-radius: 8px; padding: 20px; text-align: left; width: 80%; margin: 0 auto;">
            <p style="margin: 0 0 10px 0; font-size: 14px; color: #334155;"><strong>REQUEST STATUS</strong></p>
            <p style="margin: 0 0 5px 0; font-size: 14px; color: #64748B;">Payment: Confirmed</p>
            <p style="margin: 0 0 5px 0; font-size: 14px; color: #64748B;">Academic Calculation: Processing</p>
            <p style="margin: 0; font-size: 14px; color: #64748B;">Report: Being Prepared</p>
        </div>
        <p style="color: #64748B; font-size: 14px; margin-top: 15px;">You don't need to submit another request. We will send you another email once your report is ready.</p>
    </td></tr>
    """
    html = _build_html_template("Navy · Processing", "#1E293B", "Your report is being prepared", body)
    return _send_email(user['email'], user['name'], "EduPointAI - Your report is processing", html)

def send_msg_report_ready(user, payment, cluster_points, results_pdf_buffer):
    inv_short = payment['transaction_id'][-8:].upper()
    attachments = [{"content": base64.b64encode(results_pdf_buffer.getvalue()).decode('utf-8'), "name": "EduPointAI_Results_Report.pdf"}]

    body = f"""
    <tr><td align="center" style="padding-bottom: 30px;">
        <p style="color: #26324D; font-size: 16px; line-height: 1.6;">Hello <strong>{user['name']}</strong>,<br><br>Congratulations! EduPointAI has completed your academic calculation and prepared your personalized results.</p>
        <div style="background-color: #F3E8FF; border: 1px solid #D8B4FE; border-radius: 8px; padding: 20px; text-align: left; width: 80%; margin: 0 auto;">
            <p style="margin: 0 0 10px 0; font-size: 14px; color: #6B21A8;"><strong>YOUR ACADEMIC SUMMARY</strong></p>
            <p style="margin: 0 0 5px 0; font-size: 14px; color: #64748B;">Student Name: {user['name']}</p>
            <p style="margin: 0 0 5px 0; font-size: 14px; color: #64748B;">Cluster Points: <strong>{cluster_points}</strong></p>
            <p style="margin: 0; font-size: 14px; color: #6B21A8;"><strong>Report Status: Completed</strong></p>
        </div>
        <p style="color: #64748B; font-size: 14px; margin-top: 15px;">Your detailed academic report containing your eligible university courses is attached as a PDF.</p>
    </td></tr>
    """
    html = _build_html_template("Green + Purple · Ready", "#7047EB", "Your academic report is ready! 🎓", body, "VIEW DASHBOARD", "https://edupointai-frontend.vercel.app/")
    return _send_email(user['email'], user['name'], "Your EduPointAI Academic Report is Ready", html, attachments)
