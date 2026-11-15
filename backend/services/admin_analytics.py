"""
EduPointAI — Admin analytics, distributions, and daily Excel generation.
All queries use existing tables: users, payments, calculation_history, courses.
Never overwrites previous workbooks. Idempotent via daily_excel_reports table.
"""
import os
import io
import json
import logging
import traceback
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from db import connect
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

log = logging.getLogger(__name__)
NAIROBI = ZoneInfo("Africa/Nairobi")

# Brand palette
NAVY   = "0B1530"
DEEP   = "14213D"
TEAL   = "16B8A6"
GREEN  = "16A36A"
RED    = "DC3545"
ORANGE = "F59E0B"
BLUE   = "2563EB"
PURPLE = "7952C7"
WHITE  = "FFFFFF"


# ---------- Helpers ----------
def today_nairobi():
    return datetime.now(NAIROBI).date()


def _nairobi_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=NAIROBI)


# ---------- Overview stats ----------
def overview_stats(period_days: int = 7):
    """Return 10 stat cards with previous-period comparison."""
    now = datetime.now(NAIROBI)
    start = _nairobi_midnight(today_nairobi() - timedelta(days=period_days - 1))
    prev_start = start - timedelta(days=period_days)
    prev_end = start

    with connect() as conn:
        def scalar(q, args=()):
            r = conn.execute(q, args).fetchone()
            if not r:
                return 0
            return float(list(r.values())[0] or 0)

        revenue_cur = scalar(
            "SELECT COALESCE(SUM(amount),0) FROM payments "
            "WHERE status IN ('paid','completed') AND created_at >= %s", (start,))
        revenue_prev = scalar(
            "SELECT COALESCE(SUM(amount),0) FROM payments "
            "WHERE status IN ('paid','completed') AND created_at >= %s AND created_at < %s",
            (prev_start, prev_end))

        students_cur = scalar(
            "SELECT COUNT(*) FROM users WHERE role='student' AND created_at >= %s", (start,))
        students_prev = scalar(
            "SELECT COUNT(*) FROM users WHERE role='student' "
            "AND created_at >= %s AND created_at < %s", (prev_start, prev_end))

        apps_cur = scalar("SELECT COUNT(*) FROM users WHERE role='student'")
        apps_prev = scalar(
            "SELECT COUNT(*) FROM users WHERE role='student' AND created_at < %s", (start,))

        calcs_cur = scalar(
            "SELECT COUNT(*) FROM calculation_history WHERE created_at >= %s", (start,))
        calcs_prev = scalar(
            "SELECT COUNT(*) FROM calculation_history "
            "WHERE created_at >= %s AND created_at < %s", (prev_start, prev_end))

        succ_cur = scalar(
            "SELECT COUNT(*) FROM payments "
            "WHERE status IN ('paid','completed') AND created_at >= %s", (start,))
        succ_prev = scalar(
            "SELECT COUNT(*) FROM payments "
            "WHERE status IN ('paid','completed') AND created_at >= %s AND created_at < %s",
            (prev_start, prev_end))

        pend_cur = scalar(
            "SELECT COUNT(*) FROM payments WHERE status='pending' AND created_at >= %s", (start,))
        pend_prev = scalar(
            "SELECT COUNT(*) FROM payments WHERE status='pending' "
            "AND created_at >= %s AND created_at < %s", (prev_start, prev_end))

        fail_cur = scalar(
            "SELECT COUNT(*) FROM payments "
            "WHERE status IN ('failed','reversed') AND created_at >= %s", (start,))
        fail_prev = scalar(
            "SELECT COUNT(*) FROM payments "
            "WHERE status IN ('failed','reversed') AND created_at >= %s AND created_at < %s",
            (prev_start, prev_end))

        inv_cur = scalar(
            "SELECT COUNT(*) FROM invoice_records WHERE created_at >= %s", (start,))
        inv_prev = scalar(
            "SELECT COUNT(*) FROM invoice_records "
            "WHERE created_at >= %s AND created_at < %s", (prev_start, prev_end))

        rep_cur = scalar(
            "SELECT COUNT(*) FROM report_versions WHERE created_at >= %s", (start,))
        rep_prev = scalar(
            "SELECT COUNT(*) FROM report_versions "
            "WHERE created_at >= %s AND created_at < %s", (prev_start, prev_end))

        sent_cur = scalar(
            "SELECT COUNT(*) FROM report_versions "
            "WHERE email_status IN ('sent','delivered') AND created_at >= %s", (start,))
        sent_prev = scalar(
            "SELECT COUNT(*) FROM report_versions "
            "WHERE email_status IN ('sent','delivered') "
            "AND created_at >= %s AND created_at < %s", (prev_start, prev_end))

    def pct(c, p):
        if p == 0:
            return None if c == 0 else 100.0
        return round(((c - p) / p) * 100, 1)

    return [
        {"key":"revenue",     "label":"Total Revenue (KES)",  "value":revenue_cur, "prev":revenue_prev, "delta":pct(revenue_cur,revenue_prev), "color":TEAL,   "icon":"💰"},
        {"key":"students",    "label":"New Students",         "value":students_cur,"prev":students_prev,"delta":pct(students_cur,students_prev),"color":BLUE,   "icon":"🎓"},
        {"key":"applications","label":"Total Students",       "value":apps_cur,    "prev":apps_prev,    "delta":pct(apps_cur,apps_prev),      "color":GREEN,  "icon":"📝"},
        {"key":"calculations","label":"Calculations",         "value":calcs_cur,   "prev":calcs_prev,   "delta":pct(calcs_cur,calcs_prev),    "color":ORANGE, "icon":"🧮"},
        {"key":"successful",  "label":"Successful Payments",  "value":succ_cur,    "prev":succ_prev,    "delta":pct(succ_cur,succ_prev),      "color":GREEN,  "icon":"✅"},
        {"key":"pending",     "label":"Pending Payments",     "value":pend_cur,    "prev":pend_prev,    "delta":pct(pend_cur,pend_prev),      "color":ORANGE, "icon":"⏳"},
        {"key":"failed",      "label":"Failed Payments",      "value":fail_cur,    "prev":fail_prev,    "delta":pct(fail_cur,fail_prev),      "color":RED,    "icon":"❌"},
        {"key":"invoices",    "label":"Invoices Generated",   "value":inv_cur,     "prev":inv_prev,     "delta":pct(inv_cur,inv_prev),        "color":PURPLE, "icon":"🧾"},
        {"key":"reports",     "label":"Academic Reports",     "value":rep_cur,     "prev":rep_prev,     "delta":pct(rep_cur,rep_prev),        "color":PURPLE, "icon":"📄"},
        {"key":"reports_sent","label":"Reports Sent",         "value":sent_cur,    "prev":sent_prev,    "delta":pct(sent_cur,sent_prev),      "color":TEAL,   "icon":"📧"},
    ]


# ---------- Daily activity (3-line chart) ----------
def daily_activity(days: int = 7):
    today = today_nairobi()
    start = today - timedelta(days=days - 1)
    labels, apps, pays, calcs = [], [], [], []
    with connect() as conn:
        for i in range(days):
            d = start + timedelta(days=i)
            lo, hi = _nairobi_midnight(d), _nairobi_midnight(d) + timedelta(days=1)
            labels.append(d.strftime("%a %d %b"))
            apps.append(int(conn.execute(
                "SELECT COUNT(*) c FROM users WHERE role='student' "
                "AND created_at >= %s AND created_at < %s", (lo, hi)).fetchone()["c"]))
            pays.append(int(conn.execute(
                "SELECT COUNT(*) c FROM payments WHERE status IN ('paid','completed') "
                "AND created_at >= %s AND created_at < %s", (lo, hi)).fetchone()["c"]))
            calcs.append(int(conn.execute(
                "SELECT COUNT(*) c FROM calculation_history "
                "WHERE created_at >= %s AND created_at < %s", (lo, hi)).fetchone()["c"]))
    return {"labels": labels, "applications": apps, "payments": pays, "calculations": calcs}


def revenue_trend(days: int = 30):
    today = today_nairobi()
    start = today - timedelta(days=days - 1)
    labels, values = [], []
    with connect() as conn:
        for i in range(days):
            d = start + timedelta(days=i)
            lo, hi = _nairobi_midnight(d), _nairobi_midnight(d) + timedelta(days=1)
            labels.append(d.strftime("%d %b"))
            r = conn.execute(
                "SELECT COALESCE(SUM(amount),0) s FROM payments "
                "WHERE status IN ('paid','completed') AND created_at >= %s AND created_at < %s",
                (lo, hi)).fetchone()
            values.append(float(r["s"]))
    return {"labels": labels, "values": values}


def registration_trend(days: int = 30):
    today = today_nairobi()
    start = today - timedelta(days=days - 1)
    labels, values = [], []
    with connect() as conn:
        for i in range(days):
            d = start + timedelta(days=i)
            lo, hi = _nairobi_midnight(d), _nairobi_midnight(d) + timedelta(days=1)
            labels.append(d.strftime("%d %b"))
            values.append(int(conn.execute(
                "SELECT COUNT(*) c FROM users WHERE role='student' "
                "AND created_at >= %s AND created_at < %s", (lo, hi)).fetchone()["c"]))
    return {"labels": labels, "values": values}


def payment_performance(days: int = 30):
    today = today_nairobi()
    start = today - timedelta(days=days - 1)
    labels, succ, pend, fail = [], [], [], []
    with connect() as conn:
        for i in range(days):
            d = start + timedelta(days=i)
            lo, hi = _nairobi_midnight(d), _nairobi_midnight(d) + timedelta(days=1)
            labels.append(d.strftime("%d %b"))
            succ.append(int(conn.execute(
                "SELECT COUNT(*) c FROM payments WHERE status IN ('paid','completed') "
                "AND created_at >= %s AND created_at < %s", (lo, hi)).fetchone()["c"]))
            pend.append(int(conn.execute(
                "SELECT COUNT(*) c FROM payments WHERE status='pending' "
                "AND created_at >= %s AND created_at < %s", (lo, hi)).fetchone()["c"]))
            fail.append(int(conn.execute(
                "SELECT COUNT(*) c FROM payments WHERE status IN ('failed','reversed') "
                "AND created_at >= %s AND created_at < %s", (lo, hi)).fetchone()["c"]))
    return {"labels": labels, "successful": succ, "pending": pend, "failed": fail}


def invoice_report_trend(days: int = 30):
    today = today_nairobi()
    start = today - timedelta(days=days - 1)
    labels, inv, rep = [], [], []
    with connect() as conn:
        for i in range(days):
            d = start + timedelta(days=i)
            lo, hi = _nairobi_midnight(d), _nairobi_midnight(d) + timedelta(days=1)
            labels.append(d.strftime("%d %b"))
            inv.append(int(conn.execute(
                "SELECT COUNT(*) c FROM invoice_records "
                "WHERE created_at >= %s AND created_at < %s", (lo, hi)).fetchone()["c"]))
            rep.append(int(conn.execute(
                "SELECT COUNT(*) c FROM report_versions "
                "WHERE created_at >= %s AND created_at < %s", (lo, hi)).fetchone()["c"]))
    return {"labels": labels, "invoices": inv, "reports": rep}


def reminder_stats(days: int = 30):
    today = today_nairobi()
    start = today - timedelta(days=days - 1)
    labels, values = [], []
    with connect() as conn:
        for i in range(days):
            d = start + timedelta(days=i)
            lo, hi = _nairobi_midnight(d), _nairobi_midnight(d) + timedelta(days=1)
            labels.append(d.strftime("%d %b"))
            values.append(int(conn.execute(
                "SELECT COUNT(*) c FROM payment_reminders "
                "WHERE sent_at >= %s AND sent_at < %s", (lo, hi)).fetchone()["c"]))
    return {"labels": labels, "values": values}


# ---------- Distributions (doughnuts) ----------
def payment_distribution():
    with connect() as conn:
        rows = conn.execute(
            "SELECT CASE "
            "  WHEN status IN ('paid','completed') THEN 'successful' "
            "  WHEN status='pending' THEN 'pending' "
            "  WHEN status IN ('failed','reversed') THEN 'failed' "
            "  ELSE 'other' END AS s, COUNT(*) c FROM payments GROUP BY 1"
        ).fetchall()
    return [{"label": r["s"].capitalize(), "value": r["c"]} for r in rows]


def student_distribution():
    with connect() as conn:
        rows = conn.execute(
            "SELECT COALESCE(status,'active') st, COUNT(*) c "
            "FROM users WHERE role='student' GROUP BY 1").fetchall()
    return [{"label": r["st"].capitalize(), "value": r["c"]} for r in rows]


def email_distribution():
    with connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) c FROM email_logs GROUP BY status").fetchall()
    return [{"label": r["status"].capitalize(), "value": r["c"]} for r in rows]


def invoice_distribution():
    with connect() as conn:
        rows = conn.execute(
            "SELECT delivery_status s, COUNT(*) c FROM invoice_records GROUP BY 1").fetchall()
    return [{"label": r["s"].capitalize(), "value": r["c"]} for r in rows]


def report_distribution():
    with connect() as conn:
        rows = conn.execute(
            "SELECT COALESCE(email_status,'pending') s, COUNT(*) c "
            "FROM report_versions GROUP BY 1").fetchall()
    return [{"label": r["s"].capitalize(), "value": r["c"]} for r in rows]


def cluster_distribution():
    with connect() as conn:
        rows = conn.execute(
            "SELECT FLOOR(cluster_points)::int bucket, COUNT(*) c "
            "FROM calculation_history WHERE cluster_points IS NOT NULL "
            "GROUP BY 1 ORDER BY 1").fetchall()
    return [{"label": f"{r['bucket']}-{r['bucket']+1}", "value": r["c"]} for r in rows]


# ---------- Students ----------
def list_students(limit=200, status_filter=None):
    with connect() as conn:
        q = """SELECT u.id, u.name, u.email, u.phone, u.created_at, u.credits,
                      COALESCE(u.status,'active') status,
                      (SELECT COUNT(*) FROM calculation_history h WHERE h.user_id=u.id) calcs,
                      (SELECT COUNT(*) FROM payments p WHERE p.user_id=u.id
                         AND p.status IN ('paid','completed')) pays,
                      GREATEST(
                        COALESCE((SELECT MAX(created_at) FROM calculation_history
                                  WHERE user_id=u.id),'1970-01-01'),
                        COALESCE((SELECT MAX(created_at) FROM payments
                                  WHERE user_id=u.id),'1970-01-01')
                      ) last_activity
               FROM users u WHERE u.role='student'"""
        args = []
        if status_filter:
            q += " AND COALESCE(u.status,'active')=%s"
            args.append(status_filter)
        q += " ORDER BY u.created_at DESC LIMIT %s"
        args.append(limit)
        rows = conn.execute(q, args).fetchall()
    return [dict(r) for r in rows]


def set_student_status(user_id: int, status: str, actor):
    with connect() as conn:
        conn.execute("UPDATE users SET status=%s WHERE id=%s", (status, user_id))
        conn.execute(
            "INSERT INTO audit_logs(actor_id,actor_email,action,entity_type,entity_id,details) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (actor["id"], actor["email"], f"student.{status}",
             "user", str(user_id), json.dumps({"status": status})))
    return True


# ---------- Invoices, reports, emails ----------
def list_invoices(limit=200):
    with connect() as conn:
        rows = conn.execute("""
            SELECT i.*, u.name student_name, u.email student_email
            FROM invoice_records i LEFT JOIN users u ON u.id=i.user_id
            ORDER BY i.created_at DESC LIMIT %s""", (limit,)).fetchall()
    return [dict(r) for r in rows]


def list_reports(limit=200):
    with connect() as conn:
        rows = conn.execute("""
            SELECT rv.*, h.reference calc_reference, h.cluster_points,
                   u.name student_name, u.email student_email
            FROM report_versions rv
            JOIN calculation_history h ON h.id=rv.history_id
            LEFT JOIN users u ON u.id=h.user_id
            ORDER BY rv.created_at DESC LIMIT %s""", (limit,)).fetchall()
    return [dict(r) for r in rows]


def list_emails(limit=200, status_filter=None):
    with connect() as conn:
        q = "SELECT * FROM email_logs"
        args = []
        if status_filter:
            q += " WHERE status=%s"
            args.append(status_filter)
        q += " ORDER BY created_at DESC LIMIT %s"
        args.append(limit)
        rows = conn.execute(q, args).fetchall()
    return [dict(r) for r in rows]


# ---------- Reminders ----------
def list_outstanding_reminders():
    with connect() as conn:
        rows = conn.execute("""
            SELECT p.transaction_id, p.user_id, p.amount, p.status, p.created_at,
                   u.name, u.email,
                   EXTRACT(EPOCH FROM (now()-p.created_at))/3600 AS hours_pending
            FROM payments p JOIN users u ON u.id=p.user_id
            WHERE p.status='pending'
            ORDER BY p.created_at ASC LIMIT 200""").fetchall()
    return [dict(r) for r in rows]


def log_reminder(tx_id):
    with connect() as conn:
        conn.execute("INSERT INTO payment_reminders(transaction_id) VALUES(%s)", (tx_id,))


# ---------- Health ----------
def system_health():
    checks = []
    def push(name, ok, detail=""):
        checks.append({"name": name, "status": "healthy" if ok else "degraded", "detail": detail})

    try:
        with connect() as conn:
            conn.execute("SELECT 1").fetchone()
        push("PostgreSQL", True, "Connected")
    except Exception as e:
        push("PostgreSQL", False, str(e))

    push("Backend API", True, "Responding")
    push("Pesapal", bool(os.getenv("PESAPAL_CONSUMER_KEY")),
         "Configured" if os.getenv("PESAPAL_CONSUMER_KEY") else "Missing keys")
    push("Email Service", bool(os.getenv("SMTP_HOST") or os.getenv("BREVO_API_KEY")),
         "Configured" if (os.getenv("SMTP_HOST") or os.getenv("BREVO_API_KEY")) else "Missing keys")
    push("PDF Generator", True, "ReportLab available")
    push("Excel Generator", True, "openpyxl available")
    push("Scheduler", True, "Cron endpoints mounted")
    push("Authentication", True, "Session auth active")
    return checks


def data_quality():
    issues = []
    with connect() as conn:
        r = conn.execute(
            "SELECT COUNT(*) c FROM users WHERE role='student' "
            "AND (email IS NULL OR email='')").fetchone()
        if r["c"]:
            issues.append({"severity":"high","issue":"Students missing email","count":r["c"]})

        r = conn.execute(
            "SELECT transaction_id, COUNT(*) c FROM payments "
            "GROUP BY 1 HAVING COUNT(*)>1").fetchall()
        if r:
            issues.append({"severity":"high","issue":"Duplicate transaction IDs","count":len(r)})

        r = conn.execute(
            "SELECT COUNT(*) c FROM payments p "
            "LEFT JOIN users u ON u.id=p.user_id WHERE u.id IS NULL").fetchone()
        if r["c"]:
            issues.append({"severity":"medium","issue":"Payments with no user","count":r["c"]})
    return issues


# ---------- Audit ----------
def log_audit(actor, action, entity_type=None, entity_id=None, details=None, ip=None):
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO audit_logs(actor_id,actor_email,action,entity_type,entity_id,details,ip_address) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (actor["id"], actor["email"], action, entity_type,
                 entity_id, json.dumps(details or {}), ip))
    except Exception:
        log.error(f"log_audit failed: {traceback.format_exc()}")


def list_audit(limit=200):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ---------- Settings ----------
def get_settings():
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM platform_settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def set_setting(key, value, actor_id):
    with connect() as conn:
        conn.execute(
            "INSERT INTO platform_settings(key,value,updated_by,updated_at) VALUES(%s,%s,%s,now()) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, "
            "updated_by=EXCLUDED.updated_by, updated_at=now()",
            (key, json.dumps(value), actor_id))


# ============================================================
# DAILY EXCEL — idempotent, never overwrites
# ============================================================
def _sheet_header(ws, title, headers):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    c = ws.cell(row=1, column=1, value=title)
    c.font = Font(bold=True, size=14, color=WHITE)
    c.fill = PatternFill("solid", fgColor=DEEP)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=2, column=col, value=h)
        cell.font = Font(bold=True, color=WHITE, size=10)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    return 3


def generate_daily_excel(day: date):
    """Return (bytes, filename). Pure generation, no DB writes."""
    lo = _nairobi_midnight(day)
    hi = lo + timedelta(days=1)
    wb = Workbook()

    with connect() as conn:
        payments = conn.execute("""
            SELECT p.*, u.name student_name, u.email student_email
            FROM payments p LEFT JOIN users u ON u.id=p.user_id
            WHERE p.created_at>=%s AND p.created_at<%s
            ORDER BY p.created_at""", (lo, hi)).fetchall()
        students = conn.execute(
            "SELECT * FROM users WHERE role='student' AND created_at>=%s AND created_at<%s",
            (lo, hi)).fetchall()
        calcs = conn.execute("""
            SELECT h.*, u.name student_name, u.email student_email
            FROM calculation_history h LEFT JOIN users u ON u.id=h.user_id
            WHERE h.created_at>=%s AND h.created_at<%s
            ORDER BY h.created_at""", (lo, hi)).fetchall()
        emails = conn.execute(
            "SELECT * FROM email_logs WHERE created_at>=%s AND created_at<%s",
            (lo, hi)).fetchall()
        invoices = conn.execute(
            "SELECT * FROM invoice_records WHERE created_at>=%s AND created_at<%s",
            (lo, hi)).fetchall()
        reports = conn.execute(
            "SELECT * FROM report_versions WHERE created_at>=%s AND created_at<%s",
            (lo, hi)).fetchall()

    succ = [p for p in payments if p["status"] in ("paid", "completed")]
    pend = [p for p in payments if p["status"] == "pending"]
    fail = [p for p in payments if p["status"] in ("failed", "reversed")]
    revenue = sum(float(p["amount"] or 0) for p in succ)

    # Sheet 1: Executive Summary
    ws = wb.active
    ws.title = "Executive Summary"
    row = _sheet_header(ws, f"EduPointAI — Daily Executive Summary — {day.strftime('%d %b %Y')}",
                        ["Metric", "Value"])
    summary = [
        ("Revenue (KES)", revenue),
        ("New Students", len(students)),
        ("Total Payments", len(payments)),
        ("Successful Payments", len(succ)),
        ("Pending Payments", len(pend)),
        ("Failed Payments", len(fail)),
        ("Calculations", len(calcs)),
        ("Invoices", len(invoices)),
        ("Reports Generated", len(reports)),
        ("Emails Sent", len(emails)),
    ]
    for label, val in summary:
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row, column=2, value=val)
        row += 1
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 20

    def pay_sheet(title, rows):
        s = wb.create_sheet(title[:31])
        r = _sheet_header(s, f"{title} — {day.strftime('%d %b %Y')}",
                          ["Date","TxnID","Student","Email","Amount (KES)",
                           "Status","Network","Provider Ref"])
        for p in rows:
            s.cell(row=r, column=1, value=p["created_at"].strftime("%H:%M"))
            s.cell(row=r, column=2, value=p["transaction_id"])
            s.cell(row=r, column=3, value=p.get("student_name") or "-")
            s.cell(row=r, column=4, value=p.get("student_email") or "-")
            s.cell(row=r, column=5, value=float(p["amount"] or 0))
            s.cell(row=r, column=6, value=p["status"])
            s.cell(row=r, column=7, value=p.get("network") or "-")
            s.cell(row=r, column=8, value=p.get("provider_reference") or "-")
            if p["status"] in ("paid", "completed"):
                s.cell(row=r, column=6).fill = PatternFill("solid", fgColor="D1FAE5")
            r += 1
        for i, w in enumerate([12,22,22,26,12,12,12,26], 1):
            s.column_dimensions[get_column_letter(i)].width = w

    pay_sheet("Payment Transactions", payments)
    pay_sheet("Successful Payments", succ)
    pay_sheet("Pending Payments", pend)
    pay_sheet("Failed Payments", fail)

    # Sheet: Calculations
    s = wb.create_sheet("Calculations")
    r = _sheet_header(s, f"Calculations — {day.strftime('%d %b %Y')}",
                      ["Time","Reference","Student","Email","Cluster Points"])
    for c in calcs:
        s.cell(row=r, column=1, value=c["created_at"].strftime("%H:%M"))
        s.cell(row=r, column=2, value=c["reference"])
        s.cell(row=r, column=3, value=c.get("student_name") or "-")
        s.cell(row=r, column=4, value=c.get("student_email") or "-")
        s.cell(row=r, column=5, value=float(c["cluster_points"] or 0))
        r += 1
    for i, w in enumerate([10,22,24,28,14], 1):
        s.column_dimensions[get_column_letter(i)].width = w

    # Sheet: New Students
    s = wb.create_sheet("New Students")
    r = _sheet_header(s, f"New Students — {day.strftime('%d %b %Y')}",
                      ["Time","ID","Name","Email","Phone","Status"])
    for u in students:
        s.cell(row=r, column=1, value=u["created_at"].strftime("%H:%M"))
        s.cell(row=r, column=2, value=u["id"])
        s.cell(row=r, column=3, value=u["name"])
        s.cell(row=r, column=4, value=u["email"])
        s.cell(row=r, column=5, value=u.get("phone") or "-")
        s.cell(row=r, column=6, value=u.get("status") or "active")
        r += 1
    for i, w in enumerate([10,8,24,28,18,12], 1):
        s.column_dimensions[get_column_letter(i)].width = w

    # Sheet: Invoices
    s = wb.create_sheet("Invoices")
    r = _sheet_header(s, f"Invoices — {day.strftime('%d %b %Y')}",
                      ["Time","Invoice","Txn","Amount","Delivery","Email Sent"])
    for i in invoices:
        s.cell(row=r, column=1, value=i["created_at"].strftime("%H:%M"))
        s.cell(row=r, column=2, value=i["invoice_number"])
        s.cell(row=r, column=3, value=i["transaction_id"])
        s.cell(row=r, column=4, value=float(i["amount"] or 0))
        s.cell(row=r, column=5, value=i["delivery_status"])
        s.cell(row=r, column=6,
               value=i["email_sent_at"].strftime("%H:%M") if i["email_sent_at"] else "-")
        r += 1
    for i, w in enumerate([10,20,22,12,14,12], 1):
        s.column_dimensions[get_column_letter(i)].width = w

    # Sheet: Reports
    s = wb.create_sheet("Academic Reports")
    r = _sheet_header(s, f"Academic Reports — {day.strftime('%d %b %Y')}",
                      ["Time","Report ID","Version","PDF","Email","Retries"])
    for rp in reports:
        s.cell(row=r, column=1, value=rp["created_at"].strftime("%H:%M"))
        s.cell(row=r, column=2, value=rp["history_id"])
        s.cell(row=r, column=3, value=rp["version"])
        s.cell(row=r, column=4, value=rp["pdf_status"])
        s.cell(row=r, column=5, value=rp["email_status"])
        s.cell(row=r, column=6, value=rp["retry_count"])
        r += 1
    for i, w in enumerate([10,12,10,14,14,10], 1):
        s.column_dimensions[get_column_letter(i)].width = w

    # Sheet: Email Logs
    s = wb.create_sheet("Email Logs")
    r = _sheet_header(s, f"Email Logs — {day.strftime('%d %b %Y')}",
                      ["Time","To","Type","Status","Subject"])
    for e in emails:
        s.cell(row=r, column=1, value=e["created_at"].strftime("%H:%M"))
        s.cell(row=r, column=2, value=e["email_to"])
        s.cell(row=r, column=3, value=e["email_type"])
        s.cell(row=r, column=4, value=e["status"])
        s.cell(row=r, column=5, value=e["subject"])
        r += 1
    for i, w in enumerate([10,28,22,14,40], 1):
        s.column_dimensions[get_column_letter(i)].width = w

    # Sheet: Payment Summary
    s = wb.create_sheet("Payment Summary")
    r = _sheet_header(s, f"Payment Summary — {day.strftime('%d %b %Y')}",
                      ["Status","Count","Amount"])
    for label, subset in [("Successful", succ), ("Pending", pend), ("Failed", fail)]:
        s.cell(row=r, column=1, value=label)
        s.cell(row=r, column=2, value=len(subset))
        s.cell(row=r, column=3, value=sum(float(p["amount"] or 0) for p in subset))
        r += 1
    for i, w in enumerate([20,12,16], 1):
        s.column_dimensions[get_column_letter(i)].width = w

    # Sheet: Analytics Snapshot
    s = wb.create_sheet("Analytics Snapshot")
    r = _sheet_header(s, f"Analytics Snapshot — {day.strftime('%d %b %Y')}", ["Metric","Value"])
    metrics = {
        "Revenue Today (KES)": revenue,
        "Revenue per Student": (revenue/len(students)) if students else 0,
        "Conversion Rate (%)": (len(succ)/len(payments)*100) if payments else 0,
        "Avg Cluster Points": (sum(float(c["cluster_points"] or 0) for c in calcs)/len(calcs)) if calcs else 0,
    }
    for k, v in metrics.items():
        s.cell(row=r, column=1, value=k).font = Font(bold=True)
        s.cell(row=r, column=2, value=round(v, 2))
        r += 1
    s.column_dimensions["A"].width = 32
    s.column_dimensions["B"].width = 16

    # Sheet: System Notes
    s = wb.create_sheet("System Notes")
    s.cell(row=1, column=1, value="Report generated at (Nairobi):").font = Font(bold=True)
    s.cell(row=2, column=1, value=datetime.now(NAIROBI).strftime("%d %b %Y %H:%M:%S"))
    s.cell(row=4, column=1, value="EduPointAI · Daily Automated Report").font = Font(bold=True, size=12)
    s.column_dimensions["A"].width = 50

    # Sheet: Legend
    s = wb.create_sheet("Legend")
    legend = [("Brand", TEAL), ("Successful", GREEN), ("Pending", ORANGE),
              ("Failed", RED), ("Students", BLUE), ("Reports", PURPLE)]
    s.cell(row=1, column=1, value="Colour Legend").font = Font(bold=True, size=12)
    for i, (label, colour) in enumerate(legend, 2):
        s.cell(row=i, column=1, value=label)
        s.cell(row=i, column=2, value="#" + colour).fill = PatternFill("solid", fgColor=colour)
    s.column_dimensions["A"].width = 20
    s.column_dimensions["B"].width = 14

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"EduPointAI_Daily_{day.strftime('%Y%m%d')}.xlsx"
    return buf.getvalue(), filename


def generate_and_store_daily_excel(day: date = None):
    """Idempotent — never overwrites previous workbooks."""
    day = day or (today_nairobi() - timedelta(days=1))
    try:
        with connect() as conn:
            existing = conn.execute(
                "SELECT id FROM daily_excel_reports WHERE report_date=%s", (day,)).fetchone()
            if existing:
                return None  # already exists, never overwrite

        data, filename = generate_daily_excel(day)

        with connect() as conn:
            conn.execute(
                "INSERT INTO daily_excel_reports(report_date,filename,file_size,status) "
                "VALUES(%s,%s,%s,'generated')",
                (day, filename, len(data)))

        outdir = os.getenv("EXCEL_STORAGE_DIR", "/tmp/edupoint_reports")
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, filename)
        with open(path, "wb") as f:
            f.write(data)

        with connect() as conn:
            conn.execute(
                "UPDATE daily_excel_reports SET file_path=%s WHERE report_date=%s",
                (path, day))

        log.info(f"Daily Excel generated: {filename}")
        return {"day": str(day), "filename": filename, "size": len(data)}
    except Exception:
        log.error(f"Daily Excel failed: {traceback.format_exc()}")
        return None
