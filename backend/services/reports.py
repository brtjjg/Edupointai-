import os
import io
import base64
from datetime import datetime
import pytz
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.colors import HexColor
from brevo import Brevo
from brevo.transactional_emails import SendTransacEmailRequestSender, SendTransacEmailRequestToItem
from db import connect
import logging

logger = logging.getLogger(__name__)

# Get Kenya Time
nairobi_tz = pytz.timezone('Africa/Nairobi')
now_nairobi = datetime.now(nairobi_tz)
today_str = now_nairobi.strftime("%Y-%m-%d")

def create_excel(data, headers, title):
    wb = Workbook()
    ws = wb.active
    ws.title = title

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for row_num, row_data in enumerate(data, 2):
        for col_num, value in enumerate(row_data, 1):
            ws.cell(row=row_num, column=col_num, value=value)

    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = (max_length + 2)
        ws.column_dimensions[column].width = adjusted_width

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer

def create_pdf(title, headers, data, summary_text):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    story = []
    
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=18, textColor=HexColor("#172554"), spaceAfter=15))
    styles.add(ParagraphStyle(name="Sub", fontName="Helvetica", fontSize=10, textColor=HexColor("#64748B"), spaceAfter=20))
    
    story.append(Paragraph(title, styles["Title"]))
    story.append(Paragraph(f"Generated on {now_nairobi.strftime('%d %b %Y at %H:%M')} (Nairobi Time)", styles["Sub"]))
    story.append(Paragraph(summary_text, styles["Normal"]))
    story.append(Spacer(1, 10*mm))
    
    table_data = [headers] + data
    t = Table(table_data, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor("#172554")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), HexColor("#F8FAFC")),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor("#CBD5E1")),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]))
    story.append(t)
    
    doc.build(story)
    buffer.seek(0)
    return buffer

def generate_and_send_reports():
    try:
        with connect() as conn:
            users = conn.execute("SELECT id, name, email, phone, credits, created_at FROM users WHERE role = 'student' ORDER BY id DESC").fetchall()
            payments = conn.execute("SELECT transaction_id, user_id, amount, plan, status, created_at FROM payments ORDER BY created_at DESC").fetchall()

        enrollment_data = []
        for u in users:
            local_time = u["created_at"].astimezone(nairobi_tz).strftime("%Y-%m-%d %H:%M")
            status = "Active" if u["credits"] >= 0 else "Inactive"
            enrollment_data.append([u["id"], u["name"], u["email"], u["phone"], u["credits"], local_time, status])

        revenue_data = []
        total_revenue = 0
        successful_payments = 0
        for p in payments:
            local_time = p["created_at"].astimezone(nairobi_tz).strftime("%Y-%m-%d %H:%M")
            amount = float(p["amount"])
            if p["status"] in ["paid", "completed"]:
                total_revenue += amount
                successful_payments += 1
            revenue_data.append([p["transaction_id"], p["user_id"], p["plan"], amount, "KES", "Pesapal", p["status"], local_time])

        summary_data = [
            ["Report Date", today_str],
            ["Total Registered Students", len(users)],
            ["Total Successful Payments", successful_payments],
            ["Total Lifetime Revenue", f"KES {total_revenue:,.2f}"],
            ["Net Revenue", f"KES {total_revenue:,.2f}"]
        ]

        ex1 = create_excel(enrollment_data, ["ID", "Name", "Email", "Phone", "Credits", "Enrollment Date", "Status"], "Enrollments")
        ex2 = create_excel(revenue_data, ["TxID", "User ID", "Plan", "Amount", "Currency", "Method", "Status", "Date"], "Revenue")
        ex3 = create_excel(summary_data, ["Metric", "Value"], "Summary")

        pdf1 = create_pdf("Student Enrollments Report", ["ID", "Name", "Email", "Enrolled On"], [r[:4] for r in enrollment_data[:50]], f"Total Students: {len(users)}")
        pdf2 = create_pdf("Revenue & Payments Report", ["TxID", "User", "Amount", "Status"], [r[:4] for r in revenue_data[:50]], f"Total Revenue: KES {total_revenue:,.2f}")

        api_key = os.getenv("BREVO_API_KEY")
        sender_email = os.getenv("SENDER_EMAIL")
        admin_email = os.getenv("ADMIN_EMAIL", "brayondueki815@gmail.com")
        
        if not api_key or not sender_email:
            logger.warning("Brevo credentials missing.")
            return False

        def to_b64(buf): return base64.b64encode(buf.getvalue()).decode('utf-8')

        attachments = [
            {"content": to_b64(ex1), "name": f"01_Student_Enrollments_{today_str}.xlsx"},
            {"content": to_b64(ex2), "name": f"02_Revenue_and_Payments_{today_str}.xlsx"},
            {"content": to_b64(ex3), "name": f"03_Daily_Business_Summary_{today_str}.xlsx"},
            {"content": to_b64(pdf1), "name": f"Enrollment_Report_{today_str}.pdf"},
            {"content": to_b64(pdf2), "name": f"Revenue_Report_{today_str}.pdf"},
        ]

        html_content = f"""
        <h2>Daily Business Report - {today_str}</h2>
        <p>Here is your automated 24-hour report for EduPoint AI.</p>
        <ul>
            <li><b>Total Students:</b> {len(users)}</li>
            <li><b>Successful Payments:</b> {successful_payments}</li>
            <li><b>Total Revenue:</b> KES {total_revenue:,.2f}</li>
        </ul>
        <p>Please find the attached Excel and PDF reports for full details.</p>
        """

        client = Brevo(api_key=api_key)
        client.transactional_emails.send_transac_email(
            subject=f"EduPoint AI - Daily Business Report ({today_str})",
            html_content=html_content,
            sender=SendTransacEmailRequestSender(email=sender_email, name="EduPoint AI Automated"),
            to=[SendTransacEmailRequestToItem(email=admin_email)],
            attachment=attachments
        )
        logger.info(f"Successfully sent automated reports to {admin_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to generate/send reports: {e}")
        return False
