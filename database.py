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

    conn.commit()
    cur.close()
    conn.close()


def _dict_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


# ---------------------------------------------------------------------------
# DEBTS
# ---------------------------------------------------------------------------

def add_debt(creditor_name, total_amount, current_amount, priority, status="Open", last_contact=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO debts (creditor_name, total_amount, current_amount, priority, status, last_contact)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (creditor_name, total_amount, current_amount, priority, status, last_contact or date.today()),
    )
    conn.commit()
    cur.close()
    conn.close()


def update_debt(debt_id, **fields):
    if not fields:
        return
    allowed = {"creditor_name", "total_amount", "current_amount", "priority", "status", "last_contact"}
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


def delete_debt(debt_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM debts WHERE id = %s", (debt_id,))
    conn.commit()
    cur.close()
    conn.close()


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


def get_debt_logs(debt_id):
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM debt_logs WHERE debt_id = %s ORDER BY date DESC, id DESC", (debt_id,))
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


def delete_pipeline(pipeline_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM pipeline WHERE id = %s", (pipeline_id,))
    conn.commit()
    cur.close()
    conn.close()


def get_pipeline():
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM pipeline ORDER BY potential_value DESC NULLS LAST")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# LIQUIDITEIT / TOTALEN
# ---------------------------------------------------------------------------

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
