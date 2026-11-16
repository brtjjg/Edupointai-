import os
import io
import base64
import logging
from datetime import datetime, timezone
import pytz
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill

# ReportLab Imports for PDFs
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.colors import HexColor

# Brevo & DB
from brevo import Brevo
from brevo.transactional_emails import (
    SendTransacEmailRequestSender,
    SendTransacEmailRequestToItem,
    SendTransacEmailRequestAttachmentItem,
)
from db import connect
from services.invoices import send_success_email_with_receipt 

logger = logging.getLogger(__name__)

NAIROBI_TZ = pytz.timezone('Africa/Nairobi')
PAID_STATUSES = {"paid", "completed", "complete", "success", "successful"}

# ==============================================================================
# PART 1: ADMIN DAILY REPORTS (Excel & Daily Digest)
# ==============================================================================

def safe_local_time(dt):
    if dt is None:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(NAIROBI_TZ).strftime("%Y-%m-%d %H:%M")

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
        ws.column_dimensions[column].width = max_length + 2

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer

def create_admin_pdf(title, headers, data, summary_text, generated_at):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    story = []
    
    title_style = ParagraphStyle(name="CustomTitle", fontName="Helvetica-Bold", fontSize=18, textColor=HexColor("#172554"), spaceAfter=15)
    sub_style = ParagraphStyle(name="CustomSub", fontName="Helvetica", fontSize=10, textColor=HexColor("#64748B"), spaceAfter=20)
    normal_style = getSampleStyleSheet()["Normal"]
    
    story.append(Paragraph(title, title_style))
    story.append(Paragraph(f"Generated on {generated_at.strftime('%d %b %Y at %H:%M')} (Nairobi Time)", sub_style))
    
    safe_summary = (summary_text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    story.append(Paragraph(safe_summary, normal_style))
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
        now_nairobi = datetime.now(NAIROBI_TZ)
        today_str = now_nairobi.strftime("%Y-%m-%d")

        with connect() as conn:
            users = conn.execute("SELECT id, name, email, phone, credits, created_at FROM users WHERE role = 'student' ORDER BY id DESC LIMIT 100").fetchall()
            payments = conn.execute("SELECT transaction_id, user_id, amount, plan, status, created_at FROM payments ORDER BY created_at DESC LIMIT 100").fetchall()

        enrollment_data = []
        for u in users:
            local_time = safe_local_time(u["created_at"])
            status = "Active" if (u["credits"] or 0) >= 0 else "Inactive"
            enrollment_data.append([u["id"], u["name"], u["email"], u["phone"], u["credits"], local_time, status])

        revenue_data = []
        total_revenue = 0.0
        successful_payments = 0
        for p in payments:
            local_time = safe_local_time(p["created_at"])
            amount = float(p["amount"] or 0)
            raw_status = (p["status"] or "").lower()
            if raw_status in PAID_STATUSES:
                total_revenue += amount
                successful_payments += 1
            revenue_data.append([p["transaction_id"], p["user_id"], p["plan"], amount, "KES", "Pesapal", p["status"], local_time])

        summary_data = [
            ["Report Date", today_str],
            ["Total Registered Students (Recent)", len(users)],
            ["Total Successful Payments (Recent)", successful_payments],
            ["Total Lifetime Revenue (Recent)", f"KES {total_revenue:,.2f}"],
            ["Net Revenue", f"KES {total_revenue:,.2f}"]
        ]

        ex1 = create_excel(enrollment_data, ["ID", "Name", "Email", "Phone", "Credits", "Enrollment Date", "Status"], "Enrollments")
        ex2 = create_excel(revenue_data, ["TxID", "User ID", "Plan", "Amount", "Currency", "Method", "Status", "Date"], "Revenue")
        ex3 = create_excel(summary_data, ["Metric", "Value"], "Summary")

        pdf1 = create_admin_pdf("Student Enrollments Report", ["ID", "Name", "Email", "Enrolled On"], [r[:4] for r in enrollment_data[:50]], f"Recent Students: {len(users)}", now_nairobi)
        pdf2 = create_admin_pdf("Revenue & Payments Report", ["TxID", "User", "Amount", "Status"], [r[:4] for r in revenue_data[:50]], f"Recent Revenue: KES {total_revenue:,.2f}", now_nairobi)

        api_key = os.getenv("BREVO_API_KEY")
        sender_email = os.getenv("SENDER_EMAIL")
        admin_email = os.getenv("ADMIN_EMAIL", "nexoraacademyhelpdesk@gmail.com")
        
        if not api_key or not sender_email:
            logger.error("Brevo credentials missing.")
            return False

        def to_b64(buf): return base64.b64encode(buf.getvalue()).decode('utf-8')

        attachments = [
            SendTransacEmailRequestAttachmentItem(content=to_b64(ex1), name=f"01_Student_Enrollments_{today_str}.xlsx"),
            SendTransacEmailRequestAttachmentItem(content=to_b64(ex2), name=f"02_Revenue_and_Payments_{today_str}.xlsx"),
            SendTransacEmailRequestAttachmentItem(content=to_b64(ex3), name=f"03_Daily_Business_Summary_{today_str}.xlsx"),
            SendTransacEmailRequestAttachmentItem(content=to_b64(pdf1), name=f"Enrollment_Report_{today_str}.pdf"),
            SendTransacEmailRequestAttachmentItem(content=to_b64(pdf2), name=f"Revenue_Report_{today_str}.pdf"),
        ]

        html_content = f"""
        <h2>Daily Business Report - {today_str}</h2>
        <p>Here is your automated 24-hour report for EduPoint AI.</p>
        <ul>
            <li><b>Recent Students:</b> {len(users)}</li>
            <li><b>Recent Successful Payments:</b> {successful_payments}</li>
            <li><b>Recent Revenue:</b> KES {total_revenue:,.2f}</li>
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

    except Exception:
        import traceback
        logger.error(f"Failed to generate/send reports: {traceback.format_exc()}")
        return False


# ==============================================================================
# PART 2: STUDENT CLUSTER REPORTS (Individual PDF Generation & Emailing)
# ==============================================================================

# Styling for Student Report
NAVY = HexColor("#0A1C3A")
BLUE = HexColor("#172554")
GOLD = HexColor("#F59E0B")
LIGHT_GRAY = HexColor("#F8FAFC")
DARK_GRAY = HexColor("#4B5563")
GREEN = HexColor("#15803D")
RED = HexColor("#DC2626")

GRADE_POINTS = {
    "A": 12, "A-": 11, "B+": 10, "B": 9, "B-": 8,
    "C+": 7, "C": 6, "C-": 5, "D+": 4, "D": 3, "D-": 2, "E": 1
}

def add_student_pdf_footer(canvas, doc):
    """Adds the footer and page number to every page of the student report."""
    canvas.saveState()
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(DARK_GRAY)
    canvas.drawString(20*mm, 15*mm, "EduPointAI | Your Education. Your Future.")
    canvas.drawRightString(190*mm, 15*mm, f"Page {doc.page}")
    canvas.restoreState()

def generate_cluster_report_pdf(user, subjects_data, all_courses):
    """
    Generates the comprehensive cluster report PDF exactly as designed in the sample.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm,
        topMargin=20*mm, bottomMargin=25*mm
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(name="ReportTitle", fontName="Helvetica-Bold", fontSize=18, textColor=NAVY, spaceAfter=5)
    subtitle_style = ParagraphStyle(name="SubTitle", fontName="Helvetica", fontSize=9, textColor=DARK_GRAY, spaceAfter=15, leading=12)
    section_style = ParagraphStyle(name="SectionHeader", fontName="Helvetica-Bold", fontSize=14, textColor=NAVY, spaceBefore=15, spaceAfter=10)
    body_style = ParagraphStyle(name="Body", fontName="Helvetica", fontSize=9, textColor=DARK_GRAY, leading=11)
    
    # 1. HEADER & STUDENT INFO
    story.append(Paragraph("Your cluster points & full course eligibility", title_style))
    story.append(Paragraph("Every course in our database, grouped by whether your cluster meets, is close to, or is below the cutoff — with the specific subjects each course requires.", subtitle_style))
    
    student_data = [
        ["STUDENT", "EMAIL", "REPORT REFERENCE"],
        [user.get('name', 'Student'), user.get('email', 'N/A'), user.get('ref', 'EP-0000')]
    ]
    t_student = Table(student_data, colWidths=[60*mm, 70*mm, 40*mm])
    t_student.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), LIGHT_GRAY),
        ('TEXTCOLOR', (0,0), (-1,0), DARK_GRAY),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('FONTNAME', (0,1), (-1,1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,1), (-1,1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('LINEBELOW', (0,0), (-1,0), 1, colors.lightgrey),
    ]))
    story.append(t_student)
    story.append(Spacer(1, 5*mm))

    # 2. CALCULATE POINTS & CATEGORIZE
    total_points = 0
    subject_table_data = [["SUBJECT", "GRADE", "POINTS"]]
    
    for item in subjects_data:
        sub = item.get("subject")
        grade = item.get("grade")
        points = GRADE_POINTS.get(grade, 0)
        total_points += points
        subject_table_data.append([sub, grade, str(points)])
        
    cluster_points = round((total_points / 84) * 48, 3)
    
    qualified, close, not_yet = [], [], []
    for c in all_courses:
        gap = cluster_points - float(c.get('cutoff', 0))
        c['gap'] = gap
        if gap >= 0: qualified.append(c)
        elif gap >= -2: close.append(c)
        else: not_yet.append(c)
            
    qualified.sort(key=lambda x: float(x['cutoff']), reverse=True)
    
    # 3. SUMMARY BOX
    summary_data = [
        ["CLUSTER POINTS", "QUALIFIED", "CLOSE (±2)", "NOT YET"],
        [str(cluster_points), str(len(qualified)), str(len(close)), str(len(not_yet))]
    ]
    t_summary = Table(summary_data, colWidths=[42*mm, 42*mm, 43*mm, 43*mm])
    t_summary.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), LIGHT_GRAY),
        ('TEXTCOLOR', (0,0), (-1,0), DARK_GRAY),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('FONTNAME', (0,1), (-1,1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,1), (-1,1), 16),
        ('TEXTCOLOR', (0,1), (0,1), NAVY),
        ('TEXTCOLOR', (1,1), (1,1), GREEN),
        ('TEXTCOLOR', (2,1), (2,1), GOLD),
        ('TEXTCOLOR', (3,1), (3,1), RED),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
    ]))
    story.append(t_summary)
    story.append(Spacer(1, 10*mm))

    # 4. SECTION 01: SUBJECT BREAKDOWN
    story.append(Paragraph("01 Your KCSE Subject Breakdown", section_style))
    t_subjects = Table(subject_table_data, colWidths=[80*mm, 40*mm, 40*mm])
    t_subjects.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), BLUE),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 9),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, LIGHT_GRAY]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_subjects)
    story.append(Spacer(1, 5*mm))
    
    formula_text = f"<b>Formula:</b> (sum of best 7 subject points ÷ 84) × 48 = ({total_points} ÷ 84) × 48 = {cluster_points}"
    story.append(Paragraph(formula_text, body_style))
    story.append(Spacer(1, 10*mm))

    # 5. SECTION 02: TOP 10 COURSES
    story.append(Paragraph("02 Top 10 Recommended Courses", section_style))
    story.append(Paragraph("These are the highest-cutoff courses you currently qualify for. Your cluster meets or exceeds their cutoffs — great choices to prioritise in KUCCPS.", subtitle_style))
    
    top_10 = qualified[:10]
    course_headers = ["COURSE", "UNIVERSITY", "CUTOFF", "GAP", "OUR", "KEY SUBJECTS REQUIRED"]
    
    top_10_data = [course_headers]
    for c in top_10:
        top_10_data.append([
            Paragraph(c['course'], body_style),
            Paragraph(c['university'], body_style),
            f"{float(c['cutoff']):.3f}",
            f"+{c['gap']:.2f}",
            c.get('duration', '4y'),
            Paragraph(c.get('subjects', 'N/A'), body_style)
        ])
        
    t_top10 = Table(top_10_data, colWidths=[35*mm, 40*mm, 20*mm, 15*mm, 10*mm, 50*mm])
    t_top10.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), BLUE),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, LIGHT_GRAY]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_top10)

    # 6. SECTION 03: ALL QUALIFYING COURSES
    story.append(PageBreak())
    story.append(Paragraph(f"03 All Courses You Qualify For ({len(qualified)})", section_style))
    story.append(Paragraph("Your cluster meets or exceeds every cutoff listed below. These are safe / competitive choices.", subtitle_style))

    all_courses_data = [course_headers]
    for c in qualified:
        all_courses_data.append([
            Paragraph(c['course'], body_style),
            Paragraph(c['university'], body_style),
            f"{float(c['cutoff']):.3f}",
            f"+{c['gap']:.2f}",
            c.get('duration', '4y'),
            Paragraph(c.get('subjects', 'N/A'), body_style)
        ])
        
    t_all = Table(all_courses_data, colWidths=[35*mm, 40*mm, 20*mm, 15*mm, 10*mm, 50*mm], repeatRows=1)
    t_all.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), BLUE),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 7.5),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, LIGHT_GRAY]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_all)

    doc.build(story, onFirstPage=add_student_pdf_footer, onLaterPages=add_student_pdf_footer)
    buffer.seek(0)
    return buffer


def process_and_send_student_report(user_id, transaction_id, payment_amount=100):
    """
    Fetches data from the database, generates the Student Cluster PDF, and emails it along with the receipt.
    Call this inside your Pesapal success callback.
    """
    try:
        with connect() as conn:
            # 1. Fetch User (CHANGED ? TO %s)
            user_row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
            if not user_row:
                logger.error(f"User {user_id} not found for report generation.")
                return False
                
            # 2. Fetch Subjects (CHANGED ? TO %s)
            subjects_rows = conn.execute(
                "SELECT subject, grade FROM user_subjects WHERE transaction_id = %s", 
                (transaction_id,)
            ).fetchall()
            
            subjects_data = [{"subject": r["subject"], "grade": r["grade"]} for r in subjects_rows] if subjects_rows else []

            # 3. Fetch all courses
            courses_rows = conn.execute(
                "SELECT course, university, cutoff, duration, subjects FROM courses"
            ).fetchall()
            
            all_courses = [
                {
                    "course": r["course"],
                    "university": r["university"],
                    "cutoff": float(r["cutoff"]) if r["cutoff"] else 0.0,
                    "duration": r.get("duration", "4y"),
                    "subjects": r.get("subjects", "N/A")
                }
                for r in courses_rows
            ]

        user_info = {
            "name": user_row["name"] if user_row else "Student",
            "email": user_row["email"] if user_row else "N/A",
            "ref": f"EP-2026-{str(transaction_id)[-6:]}" 
        }

        # 4. Generate PDF
        results_pdf_buffer = generate_cluster_report_pdf(
            user=user_info, 
            subjects_data=subjects_data, 
            all_courses=all_courses
        )

        # 5. Send Email (Using the function from invoices.py)
        payment_data = {"transaction_id": transaction_id, "amount": payment_amount}
        
        logger.info(f"Sending email with Results PDF and Receipt to {user_info['email']}")
        return send_success_email_with_receipt(
            user=user_info, 
            payment=payment_data, 
            results_pdf_buffer=results_pdf_buffer
        )

    except Exception as e:
        import traceback
        logger.error(f"Error generating/sending student report: {traceback.format_exc()}")
        return False
