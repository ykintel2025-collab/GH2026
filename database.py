"""
database.py
Postgres (Supabase) data-laag voor het High-Performance Asset Management dashboard.
Verwacht een connectiestring in st.secrets["DB_URL"].
"""

import psycopg2
import psycopg2.extras
import streamlit as st
from datetime import date


def get_connection():
    """Open een connectie met de Supabase Postgres-database."""
    return psycopg2.connect(st.secrets["DB_URL"])


def init_db():
    """Maak de tabellen aan als ze nog niet bestaan. Veilig om elke start te draaien."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS debts (
            id SERIAL PRIMARY KEY,
            creditor_name TEXT NOT NULL,
            total_amount NUMERIC,
            current_amount NUMERIC NOT NULL DEFAULT 0,
            priority TEXT DEFAULT 'B',
            status TEXT NOT NULL DEFAULT 'Open',
            last_contact DATE
        )
    """)

    # NAW- en contactgegevens toevoegen aan bestaande installaties (veilig, idempotent)
    for col_def in [
        "address TEXT",
        "postal_code TEXT",
        "city TEXT",
        "phone TEXT",
        "email TEXT",
    ]:
        cur.execute(f"ALTER TABLE debts ADD COLUMN IF NOT EXISTS {col_def}")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS debt_logs (
            id SERIAL PRIMARY KEY,
            debt_id INTEGER NOT NULL REFERENCES debts(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            note TEXT,
            logged_by TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS income (
            id SERIAL PRIMARY KEY,
            source TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            date DATE NOT NULL,
            type TEXT DEFAULT 'Private',
            entered_by TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pipeline (
            id SERIAL PRIMARY KEY,
            company TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Lead',
            potential_value NUMERIC,
            next_action TEXT,
            owner TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            debt_id INTEGER NOT NULL REFERENCES debts(id) ON DELETE CASCADE,
            amount NUMERIC NOT NULL,
            date DATE NOT NULL,
            logged_by TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            assigned_to TEXT NOT NULL,
            due_date DATE,
            related_debt_id INTEGER REFERENCES debts(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            created_by TEXT,
            created_at TIMESTAMP DEFAULT now()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS message_templates (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            channel TEXT NOT NULL,
            subject TEXT,
            body TEXT NOT NULL,
            created_by TEXT
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


def _dict_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


# ---------------------------------------------------------------------------
# DEBTS
# ---------------------------------------------------------------------------

def add_debt(creditor_name, total_amount, current_amount, priority, status="Open", last_contact=None,
             address=None, postal_code=None, city=None, phone=None, email=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO debts (creditor_name, total_amount, current_amount, priority, status, last_contact,
                               address, postal_code, city, phone, email)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (creditor_name, total_amount, current_amount, priority, status, last_contact or date.today(),
         address, postal_code, city, phone, email),
    )
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


def update_debt(debt_id, **fields):
    if not fields:
        return
    allowed = {
        "creditor_name", "total_amount", "current_amount", "priority", "status", "last_contact",
        "address", "postal_code", "city", "phone", "email",
    }
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    set_clause = ", ".join(f"{k} = %s" for k in keys)
    values = [fields[k] for k in keys]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE debts SET {set_clause} WHERE id = %s", (*values, debt_id))
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


def delete_debt(debt_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM debts WHERE id = %s", (debt_id,))
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


@st.cache_data(ttl=30, show_spinner=False)
def get_debts(status=None):
    conn = get_connection()
    cur = _dict_cursor(conn)
    if status:
        cur.execute(
            "SELECT * FROM debts WHERE status = %s ORDER BY priority ASC, current_amount DESC", (status,)
        )
    else:
        cur.execute("SELECT * FROM debts ORDER BY priority ASC, current_amount DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# DEBT LOGS
# ---------------------------------------------------------------------------

def add_debt_log(debt_id, note, logged_by, log_date=None):
    log_date = log_date or date.today()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO debt_logs (debt_id, date, note, logged_by) VALUES (%s, %s, %s, %s)",
        (debt_id, log_date, note, logged_by),
    )
    cur.execute("UPDATE debts SET last_contact = %s WHERE id = %s", (log_date, debt_id))
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


@st.cache_data(ttl=30, show_spinner=False)
def get_debt_logs(debt_id):
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM debt_logs WHERE debt_id = %s ORDER BY date DESC, id DESC", (debt_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@st.cache_data(ttl=30, show_spinner=False)
def get_all_debt_logs():
    """Haalt ALLE communicatie-logs in één keer op (i.p.v. per schuld apart)."""
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM debt_logs ORDER BY date DESC, id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# INCOME
# ---------------------------------------------------------------------------

def add_income(source, amount, income_type, entered_by, income_date=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO income (source, amount, date, type, entered_by) VALUES (%s, %s, %s, %s, %s)",
        (source, amount, income_date or date.today(), income_type, entered_by),
    )
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


@st.cache_data(ttl=30, show_spinner=False)
def get_income():
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM income ORDER BY date DESC, id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def delete_income(income_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM income WHERE id = %s", (income_id,))
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


# ---------------------------------------------------------------------------
# PIPELINE
# ---------------------------------------------------------------------------

def add_pipeline(company, status, potential_value, next_action, owner):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO pipeline (company, status, potential_value, next_action, owner) VALUES (%s, %s, %s, %s, %s)",
        (company, status, potential_value, next_action, owner),
    )
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


def update_pipeline(pipeline_id, **fields):
    if not fields:
        return
    allowed = {"company", "status", "potential_value", "next_action", "owner"}
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    set_clause = ", ".join(f"{k} = %s" for k in keys)
    values = [fields[k] for k in keys]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE pipeline SET {set_clause} WHERE id = %s", (*values, pipeline_id))
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


def delete_pipeline(pipeline_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM pipeline WHERE id = %s", (pipeline_id,))
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


@st.cache_data(ttl=30, show_spinner=False)
def get_pipeline():
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM pipeline ORDER BY potential_value DESC NULLS LAST")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# PAYMENTS (betalingen)
# ---------------------------------------------------------------------------

def add_payment(debt_id, amount, logged_by, payment_date=None):
    """Registreert een betaling en trekt het bedrag automatisch af van current_amount.
    Als de schuld daarmee op 0 (of lager) komt, wordt de status automatisch 'Paid'."""
    payment_date = payment_date or date.today()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO payments (debt_id, amount, date, logged_by) VALUES (%s, %s, %s, %s)",
        (debt_id, amount, payment_date, logged_by),
    )
    cur.execute(
        """UPDATE debts
           SET current_amount = GREATEST(current_amount - %s, 0),
               status = CASE WHEN current_amount - %s <= 0 THEN 'Paid' ELSE status END,
               last_contact = %s
           WHERE id = %s""",
        (amount, amount, payment_date, debt_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


@st.cache_data(ttl=30, show_spinner=False)
def get_payments(debt_id):
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM payments WHERE debt_id = %s ORDER BY date DESC, id DESC", (debt_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@st.cache_data(ttl=30, show_spinner=False)
def get_all_payments():
    """Haalt ALLE betalingen in één keer op (i.p.v. per schuld apart)."""
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM payments ORDER BY date DESC, id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@st.cache_data(ttl=30, show_spinner=False)
def get_total_paid():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM payments")
    total = float(cur.fetchone()[0])
    cur.close()
    conn.close()
    return total


# ---------------------------------------------------------------------------
# TASKS (taken / acties)
# ---------------------------------------------------------------------------

def add_task(title, assigned_to, created_by, description=None, due_date=None, related_debt_id=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO tasks (title, description, assigned_to, due_date, related_debt_id, created_by)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (title, description, assigned_to, due_date, related_debt_id, created_by),
    )
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


def update_task(task_id, **fields):
    if not fields:
        return
    allowed = {"title", "description", "assigned_to", "due_date", "related_debt_id", "status"}
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    set_clause = ", ".join(f"{k} = %s" for k in keys)
    values = [fields[k] for k in keys]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE tasks SET {set_clause} WHERE id = %s", (*values, task_id))
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


def delete_task(task_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


@st.cache_data(ttl=30, show_spinner=False)
def get_tasks(assigned_to=None, status=None):
    conn = get_connection()
    cur = _dict_cursor(conn)
    query = """
        SELECT t.*, d.creditor_name
        FROM tasks t
        LEFT JOIN debts d ON d.id = t.related_debt_id
        WHERE 1=1
    """
    params = []
    if assigned_to:
        query += " AND t.assigned_to = %s"
        params.append(assigned_to)
    if status:
        query += " AND t.status = %s"
        params.append(status)
    query += " ORDER BY t.due_date ASC NULLS LAST, t.id DESC"
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@st.cache_data(ttl=15, show_spinner=False)
def get_dashboard_tasks(user):
    """Taken voor het dashboard: vandaag, achterstallig, en binnenkort (7 dagen) voor deze gebruiker."""
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute(
        """
        SELECT t.*, d.creditor_name
        FROM tasks t
        LEFT JOIN debts d ON d.id = t.related_debt_id
        WHERE t.assigned_to = %s AND t.status = 'Open'
          AND (t.due_date IS NULL OR t.due_date <= CURRENT_DATE + INTERVAL '7 days')
        ORDER BY t.due_date ASC NULLS LAST, t.id DESC
        """,
        (user,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# ACTIVITEIT (voor dashboard)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=15, show_spinner=False)
def get_recent_activity(limit=8):
    """Combineert recente communicatie-logs en betalingen tot één activiteitenlijst."""
    conn = get_connection()
    cur = _dict_cursor(conn)

    cur.execute(
        """SELECT dl.date, dl.note, dl.logged_by, d.creditor_name
           FROM debt_logs dl JOIN debts d ON d.id = dl.debt_id
           ORDER BY dl.date DESC, dl.id DESC LIMIT %s""",
        (limit,),
    )
    logs = [dict(r) for r in cur.fetchall()]
    for l in logs:
        l["kind"] = "log"

    cur.execute(
        """SELECT p.date, p.amount, p.logged_by, d.creditor_name
           FROM payments p JOIN debts d ON d.id = p.debt_id
           ORDER BY p.date DESC, p.id DESC LIMIT %s""",
        (limit,),
    )
    payments = [dict(r) for r in cur.fetchall()]
    for p in payments:
        p["kind"] = "payment"

    cur.close()
    conn.close()

    combined = logs + payments
    combined.sort(key=lambda x: x["date"], reverse=True)
    return combined[:limit]


# ---------------------------------------------------------------------------
# MESSAGE TEMPLATES (standaardberichten voor mail & WhatsApp)
# ---------------------------------------------------------------------------

def add_template(name, channel, body, created_by, subject=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO message_templates (name, channel, subject, body, created_by) VALUES (%s, %s, %s, %s, %s)",
        (name, channel, subject, body, created_by),
    )
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


def delete_template(template_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM message_templates WHERE id = %s", (template_id,))
    conn.commit()
    cur.close()
    conn.close()
    st.cache_data.clear()


@st.cache_data(ttl=60, show_spinner=False)
def get_templates(channel=None):
    conn = get_connection()
    cur = _dict_cursor(conn)
    if channel:
        cur.execute("SELECT * FROM message_templates WHERE channel = %s ORDER BY name", (channel,))
    else:
        cur.execute("SELECT * FROM message_templates ORDER BY channel, name")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# LIQUIDITEIT / TOTALEN
# ---------------------------------------------------------------------------

@st.cache_data(ttl=15, show_spinner=False)
def get_totals():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(current_amount), 0) FROM debts WHERE status != 'Paid'")
    total_debt_current = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(total_amount), 0) FROM debts")
    total_debt_original = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM income")
    total_income = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(potential_value), 0) FROM pipeline WHERE status != 'Deal'")
    pipeline_potential = cur.fetchone()[0]
    cur.close()
    conn.close()
    total_debt_current = float(total_debt_current)
    total_income = float(total_income)
    return {
        "total_debt_current": total_debt_current,
        "total_debt_original": float(total_debt_original),
        "total_income": total_income,
        "pipeline_potential": float(pipeline_potential),
        "net_position": total_income - total_debt_current,
    }
