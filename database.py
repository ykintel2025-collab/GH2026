"""
database.py
Postgres (Supabase) data-laag voor het High-Performance Asset Management dashboard.
Verwacht een connectiestring in st.secrets["DB_URL"].
"""

import psycopg2
import psycopg2.extras
import psycopg2.errors
import psycopg2.pool
import streamlit as st
import time
from datetime import date


@st.cache_resource
def _get_pool():
    """Eén hergebruikte pool van databaseverbindingen i.p.v. voor elke aanroep een nieuwe
    verbinding opzetten (dat laatste kost telkens een handshake naar Supabase, en was
    een belangrijke oorzaak van traagheid). ThreadedConnectionPool i.p.v. SimpleConnectionPool,
    omdat meerdere gebruikers (Ibrahim/Seal/Glenn) tegelijk in de app kunnen zitten."""
    return psycopg2.pool.ThreadedConnectionPool(1, 5, st.secrets["DB_URL"])


def _record_db_time(elapsed):
    """Houdt bij hoeveel tijd er in totaal (deze pagina-lading) naar databaseverbindingen
    gaat — puur voor het meten van de traagheid, geen functionele rol."""
    st.session_state["_db_time_total"] = st.session_state.get("_db_time_total", 0.0) + elapsed
    st.session_state["_db_call_count"] = st.session_state.get("_db_call_count", 0) + 1


def get_connection():
    """Haalt een verbinding uit de pool, en controleert eerst of die nog werkt. Serverless
    databases zoals Neon 'slapen' na een periode van inactiviteit — een verbinding die daarvan
    dateert is dan stukgegaan. Zonder deze controle zou de app daar foutmeldingen op geven of
    onnodig traag worden. Gebruik altijd samen met release_connection(conn)."""
    _t0 = time.time()
    pool = _get_pool()
    for _ in range(2):
        conn = pool.getconn()
        try:
            if not conn.closed:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                _record_db_time(time.time() - _t0)
                return conn
        except Exception:
            pass
        # Verbinding is stuk/verouderd: weggooien (niet teruggeven aan de pool) en opnieuw proberen
        try:
            pool.putconn(conn, close=True)
        except Exception:
            pass
    # Laatste redmiddel: een verse, rechtstreekse verbinding buiten de pool om
    result = psycopg2.connect(st.secrets["DB_URL"])
    _record_db_time(time.time() - _t0)
    return result


def release_connection(conn):
    """Geeft een verbinding terug aan de pool i.p.v. 'm af te sluiten. Sluit 'm gewoon direct
    af als de pool 'm niet herkent (kan bij het zeldzame redmiddel-geval in get_connection)."""
    try:
        _get_pool().putconn(conn)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


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

    # ---- CONTACTEN (generiek: schuldeisers, hulpverlening, accountants, etc.) ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            contact_type TEXT,
            organization TEXT,
            address TEXT,
            postal_code TEXT,
            city TEXT,
            phone TEXT,
            email TEXT,
            notes TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT now()
        )
    """)

    cur.execute("ALTER TABLE debts ADD COLUMN IF NOT EXISTS contact_id INTEGER REFERENCES contacts(id)")
    cur.execute("ALTER TABLE debts ADD COLUMN IF NOT EXISTS payment_agreement TEXT")
    cur.execute("ALTER TABLE debts ADD COLUMN IF NOT EXISTS next_payment_date DATE")
    cur.execute("ALTER TABLE debts ADD COLUMN IF NOT EXISTS repayment_amount NUMERIC")
    cur.execute("ALTER TABLE debts ADD COLUMN IF NOT EXISTS repayment_frequency TEXT DEFAULT 'Eenmalig'")

    # Eenmalige migratie: bestaande schulden zonder contact_id krijgen automatisch een contact aangemaakt
    cur.execute("""
        SELECT id, creditor_name, address, postal_code, city, phone, email
        FROM debts WHERE contact_id IS NULL
    """)
    to_migrate = cur.fetchall()
    for (old_id, name, address, postal_code, city, phone, email) in to_migrate:
        cur.execute(
            """INSERT INTO contacts (name, contact_type, address, postal_code, city, phone, email)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (name, "Schuldeiser", address, postal_code, city, phone, email),
        )
        new_contact_id = cur.fetchone()[0]
        cur.execute("UPDATE debts SET contact_id = %s WHERE id = %s", (new_contact_id, old_id))

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
        CREATE TABLE IF NOT EXISTS contact_logs (
            id SERIAL PRIMARY KEY,
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
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
        CREATE TABLE IF NOT EXISTS revenue_streams (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            budgeted_amount NUMERIC DEFAULT 0,
            year INTEGER,
            notes TEXT
        )
    """)
    cur.execute("ALTER TABLE revenue_streams ADD COLUMN IF NOT EXISTS amount_per_occurrence NUMERIC")
    cur.execute("ALTER TABLE revenue_streams ADD COLUMN IF NOT EXISTS frequency TEXT DEFAULT 'Maandelijks'")
    cur.execute("ALTER TABLE revenue_streams ADD COLUMN IF NOT EXISTS start_date DATE")

    cur.execute("ALTER TABLE income ADD COLUMN IF NOT EXISTS stream_id INTEGER REFERENCES revenue_streams(id)")
    cur.execute("ALTER TABLE income ADD COLUMN IF NOT EXISTS frequency TEXT DEFAULT 'Eenmalig'")
    cur.execute("ALTER TABLE income ADD COLUMN IF NOT EXISTS is_test BOOLEAN DEFAULT FALSE")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS running_costs (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            amount NUMERIC NOT NULL,
            frequency TEXT DEFAULT 'Maandelijks',
            payable_to TEXT,
            status TEXT NOT NULL DEFAULT 'Open',
            due_date DATE,
            notes TEXT,
            created_by TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS private_expenses (
            id SERIAL PRIMARY KEY,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            amount_monthly NUMERIC DEFAULT 0,
            amount_yearly NUMERIC DEFAULT 0,
            created_by TEXT
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
    cur.execute("ALTER TABLE pipeline ADD COLUMN IF NOT EXISTS deal_type TEXT DEFAULT 'Business'")
    cur.execute("ALTER TABLE pipeline ADD COLUMN IF NOT EXISTS expected_date DATE")
    cur.execute("ALTER TABLE pipeline ADD COLUMN IF NOT EXISTS frequency TEXT DEFAULT 'Eenmalig'")

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
    cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS related_contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL")
    cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS notes TEXT")

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id SERIAL PRIMARY KEY,
            filename TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
            uploaded_by TEXT,
            uploaded_at TIMESTAMP DEFAULT now(),
            file_size INTEGER,
            notes TEXT
        )
    """)
    cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL")

    # Indexen op veelgebruikte koppelkolommen — zonder deze moet de database bij elke
    # opzoeking (bijv. 'alle documenten van dit contact') de hele tabel doorzoeken.
    cur.execute("CREATE INDEX IF NOT EXISTS idx_debts_contact_id ON debts(contact_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_debt_logs_debt_id ON debt_logs(debt_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contact_logs_contact_id ON contact_logs(contact_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_debt_id ON payments(debt_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_related_debt_id ON tasks(related_debt_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_related_contact_id ON tasks(related_contact_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_contact_id ON documents(contact_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_income_stream_id ON income(stream_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_deal_type ON pipeline(deal_type)")

    conn.commit()
    cur.close()
    release_connection(conn)


def _dict_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


# ---------------------------------------------------------------------------
# DEBTS
# ---------------------------------------------------------------------------

def add_debt(contact_id, total_amount, current_amount, priority, status="Open", last_contact=None, payment_agreement=None):
    """Maakt een schuld aan, gekoppeld aan een bestaand contact (zie add_contact)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO debts (creditor_name, contact_id, total_amount, current_amount, priority, status, last_contact, payment_agreement)
           VALUES ((SELECT name FROM contacts WHERE id = %s), %s, %s, %s, %s, %s, %s, %s)""",
        (contact_id, contact_id, total_amount, current_amount, priority, status, last_contact or date.today(), payment_agreement),
    )
    conn.commit()
    cur.close()
    release_connection(conn)
    get_debts.clear()
    get_totals.clear()


def update_debt(debt_id, **fields):
    if not fields:
        return
    allowed = {
        "contact_id", "total_amount", "current_amount", "priority", "status", "last_contact",
        "payment_agreement", "next_payment_date", "repayment_amount", "repayment_frequency",
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
    release_connection(conn)
    get_debts.clear()
    get_totals.clear()


def delete_debt(debt_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM debts WHERE id = %s", (debt_id,))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_debts.clear()
    get_totals.clear()


@st.cache_data(ttl=90, show_spinner=False)
def get_debts(status=None):
    """Schulden inclusief actuele contactgegevens (via contact_id)."""
    conn = get_connection()
    cur = _dict_cursor(conn)
    base_query = """
        SELECT d.id, d.contact_id, d.total_amount, d.current_amount, d.priority, d.status, d.last_contact,
               d.payment_agreement, d.next_payment_date, d.repayment_amount, d.repayment_frequency,
               c.name AS creditor_name, c.contact_type, c.organization,
               c.address, c.postal_code, c.city, c.phone, c.email
        FROM debts d
        LEFT JOIN contacts c ON c.id = d.contact_id
    """
    if status:
        cur.execute(base_query + " WHERE d.status = %s ORDER BY d.priority ASC, d.current_amount DESC", (status,))
    else:
        cur.execute(base_query + " ORDER BY d.priority ASC, d.current_amount DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return rows


# ---------------------------------------------------------------------------
# CONTACTEN (schuldeisers, hulpverlening, accountants, overige partijen)
# ---------------------------------------------------------------------------

def add_contact(name, contact_type=None, organization=None, address=None, postal_code=None,
                 city=None, phone=None, email=None, notes=None, created_by=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO contacts (name, contact_type, organization, address, postal_code, city, phone, email, notes, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (name, contact_type, organization, address, postal_code, city, phone, email, notes, created_by),
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    release_connection(conn)
    get_contacts.clear()
    get_contact_types.clear()
    return new_id


def update_contact(contact_id, **fields):
    if not fields:
        return
    allowed = {"name", "contact_type", "organization", "address", "postal_code", "city", "phone", "email", "notes"}
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    set_clause = ", ".join(f"{k} = %s" for k in keys)
    values = [fields[k] for k in keys]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE contacts SET {set_clause} WHERE id = %s", (*values, contact_id))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_contacts.clear()
    get_contact_types.clear()
    get_debts.clear()


def delete_contact(contact_id):
    """Verwijdert een contact. Mislukt als er nog een schuld aan gekoppeld is (bescherming tegen dataverlies)."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM contacts WHERE id = %s", (contact_id,))
        conn.commit()
        get_contacts.clear()
        get_contact_types.clear()
        return True, None
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        return False, "Dit contact is nog gekoppeld aan een schuld en kan niet verwijderd worden."
    finally:
        cur.close()
        release_connection(conn)


@st.cache_data(ttl=60, show_spinner=False)
def get_contacts(contact_type=None):
    conn = get_connection()
    cur = _dict_cursor(conn)
    if contact_type:
        cur.execute("SELECT * FROM contacts WHERE contact_type = %s ORDER BY name", (contact_type,))
    else:
        cur.execute("SELECT * FROM contacts ORDER BY name")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return rows


@st.cache_data(ttl=60, show_spinner=False)
def get_contact_types():
    """Alle types die al eens gebruikt zijn, voor een dropdown met vrije invoer."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT contact_type FROM contacts WHERE contact_type IS NOT NULL ORDER BY contact_type")
    types = [r[0] for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return types


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
    release_connection(conn)
    get_debt_logs.clear()
    get_all_debt_logs.clear()
    get_recent_activity.clear()
    get_debts.clear()


@st.cache_data(ttl=90, show_spinner=False)
def get_debt_logs(debt_id):
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM debt_logs WHERE debt_id = %s ORDER BY date DESC, id DESC", (debt_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return rows


@st.cache_data(ttl=90, show_spinner=False)
def get_all_debt_logs():
    """Haalt ALLE communicatie-logs in één keer op (i.p.v. per schuld apart)."""
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM debt_logs ORDER BY date DESC, id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return rows


def add_contact_log(contact_id, note, logged_by, log_date=None):
    """Algemene communicatielog per contact — voor iedereen, ook contacten zonder schuld
    (bijv. een accountant of hulpverlener): notities, telefoontjes, acties."""
    log_date = log_date or date.today()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO contact_logs (contact_id, date, note, logged_by) VALUES (%s, %s, %s, %s)",
        (contact_id, log_date, note, logged_by),
    )
    conn.commit()
    cur.close()
    release_connection(conn)
    get_contact_logs.clear()
    get_all_contact_logs.clear()
    get_recent_activity.clear()


def delete_contact_log(log_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM contact_logs WHERE id = %s", (log_id,))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_contact_logs.clear()
    get_all_contact_logs.clear()


@st.cache_data(ttl=90, show_spinner=False)
def get_contact_logs(contact_id):
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM contact_logs WHERE contact_id = %s ORDER BY date DESC, id DESC", (contact_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return rows


@st.cache_data(ttl=90, show_spinner=False)
def get_all_contact_logs():
    """Haalt ALLE contact-logs in één keer op (i.p.v. per contact apart) — voorkomt tientallen
    losse databasebevragingen wanneer de Contacten-pagina met veel contacten wordt geladen."""
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM contact_logs ORDER BY date DESC, id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return rows


# ---------------------------------------------------------------------------
# INCOME
# ---------------------------------------------------------------------------

def add_income(source, amount, income_type, entered_by, income_date=None, stream_id=None,
                frequency="Eenmalig", is_test=False):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO income (source, amount, date, type, entered_by, stream_id, frequency, is_test)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (source, amount, income_date or date.today(), income_type, entered_by, stream_id, frequency, is_test),
    )
    conn.commit()
    cur.close()
    release_connection(conn)
    get_income.clear()
    get_revenue_overview.clear()
    get_totals.clear()


@st.cache_data(ttl=90, show_spinner=False)
def get_income():
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM income ORDER BY date DESC, id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return rows


def update_income(income_id, **fields):
    if not fields:
        return
    allowed = {"source", "amount", "date", "type", "stream_id", "frequency", "is_test"}
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    set_clause = ", ".join(f"{k} = %s" for k in keys)
    values = [fields[k] for k in keys]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE income SET {set_clause} WHERE id = %s", (*values, income_id))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_income.clear()
    get_revenue_overview.clear()
    get_totals.clear()


def delete_income(income_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM income WHERE id = %s", (income_id,))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_income.clear()
    get_revenue_overview.clear()
    get_totals.clear()


# ---------------------------------------------------------------------------
# REVENUE STREAMS (opbrengsten: begroot vs. werkelijk + prognose-planning)
# ---------------------------------------------------------------------------

def add_revenue_stream(name, budgeted_amount, year=None, notes=None,
                        amount_per_occurrence=None, frequency="Maandelijks", start_date=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO revenue_streams (name, budgeted_amount, year, notes, amount_per_occurrence, frequency, start_date)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (name, budgeted_amount, year, notes, amount_per_occurrence, frequency, start_date),
    )
    conn.commit()
    cur.close()
    release_connection(conn)
    get_revenue_streams.clear()
    get_revenue_overview.clear()


def update_revenue_stream(stream_id, **fields):
    if not fields:
        return
    allowed = {"name", "budgeted_amount", "year", "notes", "amount_per_occurrence", "frequency", "start_date"}
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    set_clause = ", ".join(f"{k} = %s" for k in keys)
    values = [fields[k] for k in keys]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE revenue_streams SET {set_clause} WHERE id = %s", (*values, stream_id))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_revenue_streams.clear()
    get_revenue_overview.clear()


def delete_revenue_stream(stream_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM revenue_streams WHERE id = %s", (stream_id,))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_revenue_streams.clear()
    get_revenue_overview.clear()


@st.cache_data(ttl=60, show_spinner=False)
def get_revenue_streams():
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM revenue_streams ORDER BY budgeted_amount DESC NULLS LAST")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return rows


@st.cache_data(ttl=90, show_spinner=False)
def get_revenue_overview():
    """Begroot vs. werkelijk gerealiseerd per opbrengstenbron."""
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("""
        SELECT rs.id, rs.name, rs.budgeted_amount,
               COALESCE(SUM(i.amount), 0) AS realized_amount
        FROM revenue_streams rs
        LEFT JOIN income i ON i.stream_id = rs.id
        GROUP BY rs.id, rs.name, rs.budgeted_amount
        ORDER BY rs.budgeted_amount DESC NULLS LAST
    """)
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["budgeted_amount"] = float(r["budgeted_amount"] or 0)
        r["realized_amount"] = float(r["realized_amount"] or 0)
    cur.close()
    release_connection(conn)
    return rows


# ---------------------------------------------------------------------------
# RUNNING COSTS (lopende kosten, incl. eigen vergoeding)
# ---------------------------------------------------------------------------

def add_running_cost(name, amount, created_by, category=None, frequency="Maandelijks",
                      payable_to=None, status="Open", due_date=None, notes=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO running_costs (name, category, amount, frequency, payable_to, status, due_date, notes, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (name, category, amount, frequency, payable_to, status, due_date, notes, created_by),
    )
    conn.commit()
    cur.close()
    release_connection(conn)
    get_running_costs.clear()


def update_running_cost(cost_id, **fields):
    if not fields:
        return
    allowed = {"name", "category", "amount", "frequency", "payable_to", "status", "due_date", "notes"}
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    set_clause = ", ".join(f"{k} = %s" for k in keys)
    values = [fields[k] for k in keys]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE running_costs SET {set_clause} WHERE id = %s", (*values, cost_id))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_running_costs.clear()


def delete_running_cost(cost_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM running_costs WHERE id = %s", (cost_id,))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_running_costs.clear()


@st.cache_data(ttl=60, show_spinner=False)
def get_running_costs(status=None):
    conn = get_connection()
    cur = _dict_cursor(conn)
    if status:
        cur.execute("SELECT * FROM running_costs WHERE status = %s ORDER BY due_date ASC NULLS LAST", (status,))
    else:
        cur.execute("SELECT * FROM running_costs ORDER BY due_date ASC NULLS LAST")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return rows


# ---------------------------------------------------------------------------
# PRIVATE EXPENSES (privé-uitgaven)
# ---------------------------------------------------------------------------

def add_private_expense(category, description, amount_monthly, created_by):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO private_expenses (category, description, amount_monthly, amount_yearly, created_by)
           VALUES (%s, %s, %s, %s, %s)""",
        (category, description, amount_monthly, amount_monthly * 12, created_by),
    )
    conn.commit()
    cur.close()
    release_connection(conn)
    get_private_expenses.clear()


def update_private_expense(expense_id, **fields):
    if not fields:
        return
    allowed = {"category", "description", "amount_monthly", "amount_yearly"}
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    if "amount_monthly" in fields and "amount_yearly" not in fields:
        fields["amount_yearly"] = fields["amount_monthly"] * 12
        keys.append("amount_yearly")
    set_clause = ", ".join(f"{k} = %s" for k in keys)
    values = [fields[k] for k in keys]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE private_expenses SET {set_clause} WHERE id = %s", (*values, expense_id))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_private_expenses.clear()


def delete_private_expense(expense_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM private_expenses WHERE id = %s", (expense_id,))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_private_expenses.clear()


@st.cache_data(ttl=60, show_spinner=False)
def get_private_expenses():
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM private_expenses ORDER BY category, description")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return rows


# ---------------------------------------------------------------------------
# PIPELINE
# ---------------------------------------------------------------------------

def add_pipeline(company, status, potential_value, next_action, owner, deal_type="Business",
                  expected_date=None, frequency="Eenmalig"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO pipeline (company, status, potential_value, next_action, owner, deal_type, expected_date, frequency)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (company, status, potential_value, next_action, owner, deal_type, expected_date, frequency),
    )
    conn.commit()
    cur.close()
    release_connection(conn)
    get_pipeline.clear()
    get_totals.clear()


def update_pipeline(pipeline_id, **fields):
    if not fields:
        return
    allowed = {"company", "status", "potential_value", "next_action", "owner", "deal_type", "expected_date", "frequency"}
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
    release_connection(conn)
    get_pipeline.clear()
    get_totals.clear()


def delete_pipeline(pipeline_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM pipeline WHERE id = %s", (pipeline_id,))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_pipeline.clear()
    get_totals.clear()


@st.cache_data(ttl=60, show_spinner=False)
def get_pipeline(deal_type=None):
    conn = get_connection()
    cur = _dict_cursor(conn)
    if deal_type:
        cur.execute("SELECT * FROM pipeline WHERE deal_type = %s ORDER BY potential_value DESC NULLS LAST", (deal_type,))
    else:
        cur.execute("SELECT * FROM pipeline ORDER BY potential_value DESC NULLS LAST")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
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
    release_connection(conn)
    get_payments.clear()
    get_all_payments.clear()
    get_total_paid.clear()
    get_debts.clear()
    get_totals.clear()
    get_recent_activity.clear()


@st.cache_data(ttl=90, show_spinner=False)
def get_payments(debt_id):
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM payments WHERE debt_id = %s ORDER BY date DESC, id DESC", (debt_id,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return rows


@st.cache_data(ttl=90, show_spinner=False)
def get_all_payments():
    """Haalt ALLE betalingen in één keer op (i.p.v. per schuld apart)."""
    conn = get_connection()
    cur = _dict_cursor(conn)
    cur.execute("SELECT * FROM payments ORDER BY date DESC, id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return rows


@st.cache_data(ttl=90, show_spinner=False)
def get_total_paid():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM payments")
    total = float(cur.fetchone()[0])
    cur.close()
    release_connection(conn)
    return total


# ---------------------------------------------------------------------------
# TASKS (taken / acties)
# ---------------------------------------------------------------------------

def add_task(title, assigned_to, created_by, description=None, due_date=None, related_debt_id=None, related_contact_id=None, notes=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO tasks (title, description, assigned_to, due_date, related_debt_id, related_contact_id, notes, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (title, description, assigned_to, due_date, related_debt_id, related_contact_id, notes, created_by),
    )
    conn.commit()
    cur.close()
    release_connection(conn)
    get_tasks.clear()
    get_dashboard_tasks.clear()


def update_task(task_id, **fields):
    if not fields:
        return
    allowed = {"title", "description", "assigned_to", "due_date", "related_debt_id", "related_contact_id", "status", "notes"}
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
    release_connection(conn)
    get_tasks.clear()
    get_dashboard_tasks.clear()


def delete_task(task_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_tasks.clear()
    get_dashboard_tasks.clear()


@st.cache_data(ttl=90, show_spinner=False)
def get_tasks(assigned_to=None, status=None):
    conn = get_connection()
    cur = _dict_cursor(conn)
    # COALESCE: een taak kan direct aan een contact gekoppeld zijn, óf indirect via een schuld
    # (die op zijn beurt aan een contact hangt) — dit haalt in beide gevallen de juiste
    # contactgegevens op, zodat je telefoon/e-mail meteen bij de taak ziet staan.
    query = """
        SELECT t.*, d.creditor_name,
               COALESCE(c.name, dc.name) AS contact_name,
               COALESCE(c.phone, dc.phone) AS contact_phone,
               COALESCE(c.email, dc.email) AS contact_email,
               COALESCE(c.id, dc.id) AS resolved_contact_id
        FROM tasks t
        LEFT JOIN debts d ON d.id = t.related_debt_id
        LEFT JOIN contacts c ON c.id = t.related_contact_id
        LEFT JOIN contacts dc ON dc.id = d.contact_id
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
    release_connection(conn)
    return rows


@st.cache_data(ttl=60, show_spinner=False)
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
    release_connection(conn)
    return rows


# ---------------------------------------------------------------------------
# ACTIVITEIT (voor dashboard)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
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

    cur.execute(
        """SELECT d.uploaded_at::date AS date, d.filename, d.uploaded_by AS logged_by, c.name AS creditor_name
           FROM documents d LEFT JOIN contacts c ON c.id = d.contact_id
           ORDER BY d.uploaded_at DESC LIMIT %s""",
        (limit,),
    )
    documents = [dict(r) for r in cur.fetchall()]
    for doc in documents:
        doc["kind"] = "document"

    cur.execute(
        """SELECT cl.date, cl.note, cl.logged_by, c.name AS creditor_name
           FROM contact_logs cl JOIN contacts c ON c.id = cl.contact_id
           ORDER BY cl.date DESC, cl.id DESC LIMIT %s""",
        (limit,),
    )
    contact_logs_rows = [dict(r) for r in cur.fetchall()]
    for cl in contact_logs_rows:
        cl["kind"] = "log"

    cur.close()
    release_connection(conn)

    combined = logs + payments + documents + contact_logs_rows
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
    release_connection(conn)
    get_templates.clear()


def delete_template(template_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM message_templates WHERE id = %s", (template_id,))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_templates.clear()


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
    release_connection(conn)
    return rows


# ---------------------------------------------------------------------------
# DOCUMENTEN (metadata; de bestanden zelf staan in Supabase Storage, zie storage.py)
# ---------------------------------------------------------------------------

def add_document(filename, storage_path, uploaded_by, contact_id=None, task_id=None, file_size=None, notes=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO documents (filename, storage_path, contact_id, task_id, uploaded_by, file_size, notes)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (filename, storage_path, contact_id, task_id, uploaded_by, file_size, notes),
    )
    conn.commit()
    cur.close()
    release_connection(conn)
    get_documents.clear()
    get_recent_activity.clear()


def update_document(document_id, **fields):
    if not fields:
        return
    allowed = {"contact_id", "task_id", "notes"}
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    set_clause = ", ".join(f"{k} = %s" for k in keys)
    values = [fields[k] for k in keys]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE documents SET {set_clause} WHERE id = %s", (*values, document_id))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_documents.clear()


def delete_document(document_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
    conn.commit()
    cur.close()
    release_connection(conn)
    get_documents.clear()


@st.cache_data(ttl=90, show_spinner=False)
def get_documents(contact_id=None):
    """contact_id=None (default) geeft ALLE documenten; geef expliciet contact_id mee voor 1 contact;
    gebruik contact_id='geen' om alleen de niet-toegewezen documenten te krijgen."""
    conn = get_connection()
    cur = _dict_cursor(conn)
    base = """
        SELECT d.*, c.name AS contact_name, t.title AS task_title
        FROM documents d
        LEFT JOIN contacts c ON c.id = d.contact_id
        LEFT JOIN tasks t ON t.id = d.task_id
    """
    if contact_id == "geen":
        cur.execute(base + " WHERE d.contact_id IS NULL ORDER BY d.uploaded_at DESC")
    elif contact_id is not None:
        cur.execute(base + " WHERE d.contact_id = %s ORDER BY d.uploaded_at DESC", (contact_id,))
    else:
        cur.execute(base + " ORDER BY d.uploaded_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    release_connection(conn)
    return rows


# ---------------------------------------------------------------------------
# LIQUIDITEIT / TOTALEN
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def get_totals():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(current_amount), 0) FROM debts WHERE status != 'Paid'")
    total_debt_current = cur.fetchone()[0]
    # Waar geen oorspronkelijke hoofdsom bekend is, tellen we het actuele bedrag als hoofdsom
    # (dan is de voortgang voor die schuld 0% i.p.v. een onzinnig negatief getal)
    cur.execute("SELECT COALESCE(SUM(COALESCE(total_amount, current_amount)), 0) FROM debts")
    total_debt_original = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM income")
    total_income = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(potential_value), 0) FROM pipeline WHERE status != 'Deal'")
    pipeline_potential = cur.fetchone()[0]
    cur.close()
    release_connection(conn)
    total_debt_current = float(total_debt_current)
    total_income = float(total_income)
    return {
        "total_debt_current": total_debt_current,
        "total_debt_original": float(total_debt_original),
        "total_income": total_income,
        "pipeline_potential": float(pipeline_potential),
        "net_position": total_income - total_debt_current,
    }
