"""
app.py
Streamlit UI voor het High-Performance Asset Management dashboard.
Draaien met: streamlit run app.py
Vereist st.secrets["DB_URL"] en st.secrets["credentials"].
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta
import database as db
import auth

st.set_page_config(page_title="Asset Management Dashboard", layout="wide", page_icon="📊")

# --- Login ---------------------------------------------------------------
current_user = auth.check_login()

# --- Database init (idempotent, veilig om elke keer te draaien) ----------
db.init_db()

PRIORITIES = ["A", "B", "C"]
STATUSES = ["Open", "Paid"]
PIPELINE_STATUSES = ["Lead", "Pitch", "Deal"]
INCOME_TYPES = ["Private", "Ambassadorship"]
ASSIGNEES = ["Ibrahim", "Seal", "Glenn"]
TASK_STATUSES = ["Open", "Done"]


def eur(x):
    try:
        return f"€ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "€ 0,00"


def prio_badge(p):
    colors = {"A": "🔴", "B": "🟡", "C": "🟢"}
    return f"{colors.get(p, '⚪')} {p}"


# --- Sidebar navigatie -----------------------------------------------------
with st.sidebar:
    st.write(f"Ingelogd als **{current_user}**")
    if st.button("Uitloggen"):
        st.session_state["authenticated"] = False
        st.session_state["user"] = None
        st.rerun()
    st.divider()
    page = st.radio(
        "Navigatie",
        ["🏠 Dashboard", "📋 Schulden", "✅ Taken", "📈 Pipeline & Inkomsten", "💧 Liquiditeit"],
        label_visibility="collapsed",
    )

# ===========================================================================
# PAGINA: DASHBOARD
# ===========================================================================
if page == "🏠 Dashboard":
    st.title(f"Welkom terug, {current_user} 👋")

    totals = db.get_totals()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Netto positie", eur(totals["net_position"]))
    c2.metric("Schulden (open)", eur(totals["total_debt_current"]))
    c3.metric("Inkomsten (totaal)", eur(totals["total_income"]))
    c4.metric("Al afgelost", eur(db.get_total_paid()))

    st.divider()

    col_taken, col_activiteit = st.columns([1.3, 1])

    with col_taken:
        st.subheader("✅ Jouw taken (komende 7 dagen)")
        my_tasks = db.get_dashboard_tasks(current_user)

        if not my_tasks:
            st.success("Niks openstaand voor jou de komende week. 🎉")
        else:
            today = date.today()
            overdue = [t for t in my_tasks if t["due_date"] and t["due_date"] < today]
            due_today = [t for t in my_tasks if t["due_date"] == today]
            upcoming = [t for t in my_tasks if t["due_date"] and t["due_date"] > today]
            no_date = [t for t in my_tasks if not t["due_date"]]

            def render_task(t):
                cols = st.columns([0.08, 0.72, 0.2])
                done = cols[0].checkbox("", key=f"dash_task_{t['id']}")
                label = f"**{t['title']}**"
                if t.get("creditor_name"):
                    label += f" — _{t['creditor_name']}_"
                if t["due_date"]:
                    label += f"  ·  {t['due_date'].strftime('%d-%m')}"
                cols[1].markdown(label)
                if t["description"]:
                    cols[1].caption(t["description"])
                if done:
                    db.update_task(t["id"], status="Done")
                    st.rerun()

            if overdue:
                st.markdown("**🔴 Achterstallig**")
                for t in overdue:
                    render_task(t)
            if due_today:
                st.markdown("**🟠 Vandaag**")
                for t in due_today:
                    render_task(t)
            if upcoming:
                st.markdown("**🔵 Binnenkort**")
                for t in upcoming:
                    render_task(t)
            if no_date:
                st.markdown("**⚪ Zonder datum**")
                for t in no_date:
                    render_task(t)

        with st.popover("➕ Snel een taak toevoegen"):
            with st.form("dash_add_task", clear_on_submit=True):
                t_title = st.text_input("Taak (bijv. 'Bel Fiscus')")
                t_assignee = st.selectbox("Toewijzen aan", ASSIGNEES, index=ASSIGNEES.index(current_user) if current_user in ASSIGNEES else 0)
                t_due = st.date_input("Deadline", value=date.today())
                t_desc = st.text_area("Toelichting (optioneel)")
                if st.form_submit_button("Taak toevoegen") and t_title:
                    db.add_task(t_title, t_assignee, current_user, description=t_desc or None, due_date=t_due)
                    st.rerun()

    with col_activiteit:
        st.subheader("🕒 Recente activiteit")
        activity = db.get_recent_activity(limit=8)
        if not activity:
            st.caption("Nog geen activiteit gelogd.")
        else:
            for a in activity:
                datum = a["date"].strftime("%d-%m")
                if a["kind"] == "payment":
                    st.write(f"💶 `{datum}` **{a['logged_by']}** registreerde een betaling van {eur(a['amount'])} bij *{a['creditor_name']}*")
                else:
                    st.write(f"📝 `{datum}` **{a['logged_by']}** noteerde bij *{a['creditor_name']}*: {a['note']}")

# ===========================================================================
# PAGINA: SCHULDEN (gecombineerd overzicht)
# ===========================================================================
elif page == "📋 Schulden":
    top1, top2 = st.columns([4, 1])
    with top1:
        st.title("Schulden Overzicht")
    with top2:
        with st.popover("➕ Nieuwe schuld"):
            with st.form("add_debt_form", clear_on_submit=True):
                creditor_name = st.text_input("Schuldeiser")
                total_amount = st.number_input("Hoofdsom oorspronkelijk", min_value=0.0, step=100.0)
                current_amount = st.number_input("Actueel bedrag", min_value=0.0, step=100.0)
                priority = st.selectbox("Prioriteit", PRIORITIES)
                if st.form_submit_button("Toevoegen") and creditor_name:
                    db.add_debt(creditor_name, total_amount, current_amount, priority)
                    st.success(f"Schuld bij {creditor_name} toegevoegd.")
                    st.rerun()

    fc1, fc2 = st.columns([1, 3])
    status_filter = fc1.radio("Filter", ["Alle", "Open", "Paid"], horizontal=True, label_visibility="collapsed")
    search = fc2.text_input("Zoek op naam", placeholder="Zoek schuldeiser...", label_visibility="collapsed")

    debts = db.get_debts(status=None if status_filter == "Alle" else status_filter)
    if search:
        debts = [d for d in debts if search.lower() in d["creditor_name"].lower()]

    if not debts:
        st.info("Geen schulden gevonden.")
    else:
        st.caption(f"{len(debts)} schuldeisers")
        for debt in debts:
            last_contact = debt["last_contact"].strftime("%d-%m-%Y") if debt["last_contact"] else "—"
            header = (
                f"{prio_badge(debt['priority'])}  **{debt['creditor_name']}**  "
                f"—  {eur(debt['current_amount'])}  ·  {debt['status']}  ·  laatst contact {last_contact}"
            )
            with st.expander(header):
                dc1, dc2, dc3, dc4 = st.columns(4)

                with dc1:
                    new_amount = st.number_input(
                        "Actueel bedrag", min_value=0.0, value=float(debt["current_amount"]),
                        step=50.0, key=f"amt_{debt['id']}",
                    )
                with dc2:
                    new_status = st.selectbox(
                        "Status", STATUSES,
                        index=STATUSES.index(debt["status"]) if debt["status"] in STATUSES else 0,
                        key=f"status_{debt['id']}",
                    )
                with dc3:
                    new_priority = st.selectbox(
                        "Prioriteit", PRIORITIES,
                        index=PRIORITIES.index(debt["priority"]) if debt["priority"] in PRIORITIES else 1,
                        key=f"prio_{debt['id']}",
                    )
                with dc4:
                    st.write("")
                    st.write("")
                    bcol1, bcol2 = st.columns(2)
                    if bcol1.button("💾 Opslaan", key=f"save_{debt['id']}"):
                        db.update_debt(debt["id"], current_amount=new_amount, status=new_status, priority=new_priority)
                        st.rerun()
                    if bcol2.button("🗑️", key=f"del_{debt['id']}", help="Schuld verwijderen"):
                        db.delete_debt(debt["id"])
                        st.rerun()

                st.divider()
                tab_log, tab_betaling, tab_taken = st.tabs(["📝 Communicatie", "💶 Betalingen", "✅ Taken"])

                with tab_log:
                    logs = db.get_debt_logs(debt["id"])
                    if logs:
                        for log in logs:
                            wie = f" — *{log['logged_by']}*" if log.get("logged_by") else ""
                            st.write(f"- `{log['date']}` {log['note']}{wie}")
                    else:
                        st.caption("Nog geen notities.")
                    with st.form(f"log_form_{debt['id']}", clear_on_submit=True):
                        note = st.text_input("Nieuwe notitie", key=f"note_{debt['id']}")
                        if st.form_submit_button("Loggen") and note:
                            db.add_debt_log(debt["id"], note, logged_by=current_user)
                            st.rerun()

                with tab_betaling:
                    payments = db.get_payments(debt["id"])
                    if payments:
                        for p in payments:
                            st.write(f"- `{p['date']}` {eur(p['amount'])} betaald — *{p['logged_by']}*")
                    else:
                        st.caption("Nog geen betalingen geregistreerd.")
                    with st.form(f"payment_form_{debt['id']}", clear_on_submit=True):
                        pcol1, pcol2 = st.columns([2, 1])
                        pay_amount = pcol1.number_input("Bedrag", min_value=0.0, step=50.0, key=f"pay_{debt['id']}")
                        pay_date = pcol2.date_input("Datum", value=date.today(), key=f"paydate_{debt['id']}")
                        if st.form_submit_button("Betaling registreren") and pay_amount > 0:
                            db.add_payment(debt["id"], pay_amount, logged_by=current_user, payment_date=pay_date)
                            st.success("Betaling geregistreerd, bedrag automatisch bijgewerkt.")
                            st.rerun()

                with tab_taken:
                    related_tasks = [t for t in db.get_tasks() if t["related_debt_id"] == debt["id"]]
                    if related_tasks:
                        for t in related_tasks:
                            status_icon = "✅" if t["status"] == "Done" else "⬜"
                            due = t["due_date"].strftime("%d-%m") if t["due_date"] else "geen datum"
                            st.write(f"{status_icon} {t['title']} — {t['assigned_to']} ({due})")
                    else:
                        st.caption("Geen taken gekoppeld aan deze schuld.")
                    with st.form(f"task_form_{debt['id']}", clear_on_submit=True):
                        tcol1, tcol2, tcol3 = st.columns(3)
                        task_title = tcol1.text_input("Taak", key=f"tasktitle_{debt['id']}", placeholder=f"Bel {debt['creditor_name']}")
                        task_assignee = tcol2.selectbox("Wie", ASSIGNEES, key=f"taskassignee_{debt['id']}")
                        task_due = tcol3.date_input("Deadline", value=date.today(), key=f"taskdue_{debt['id']}")
                        if st.form_submit_button("Taak toevoegen") and task_title:
                            db.add_task(task_title, task_assignee, current_user, due_date=task_due, related_debt_id=debt["id"])
                            st.rerun()

# ===========================================================================
# PAGINA: TAKEN (volledig beheer)
# ===========================================================================
elif page == "✅ Taken":
    st.title("Taken & Acties")

    with st.popover("➕ Nieuwe taak"):
        with st.form("new_task_form", clear_on_submit=True):
            title = st.text_input("Titel")
            assignee = st.selectbox("Toewijzen aan", ASSIGNEES)
            due = st.date_input("Deadline", value=date.today())
            desc = st.text_area("Toelichting (optioneel)")
            debts_all = db.get_debts()
            debt_options = {"— geen —": None}
            debt_options.update({d["creditor_name"]: d["id"] for d in debts_all})
            linked = st.selectbox("Koppelen aan schuldeiser (optioneel)", list(debt_options.keys()))
            if st.form_submit_button("Toevoegen") and title:
                db.add_task(title, assignee, current_user, description=desc or None, due_date=due, related_debt_id=debt_options[linked])
                st.rerun()

    fcol1, fcol2 = st.columns(2)
    filter_assignee = fcol1.selectbox("Filter op persoon", ["Iedereen"] + ASSIGNEES)
    filter_status = fcol2.selectbox("Filter op status", ["Alle", "Open", "Done"])

    tasks = db.get_tasks(
        assigned_to=None if filter_assignee == "Iedereen" else filter_assignee,
        status=None if filter_status == "Alle" else filter_status,
    )

    if not tasks:
        st.info("Geen taken gevonden.")
    else:
        for t in tasks:
            cols = st.columns([0.06, 0.5, 0.15, 0.15, 0.14])
            done = cols[0].checkbox("", value=(t["status"] == "Done"), key=f"taskpage_{t['id']}")
            title_txt = f"~~{t['title']}~~" if t["status"] == "Done" else f"**{t['title']}**"
            if t.get("creditor_name"):
                title_txt += f" — _{t['creditor_name']}_"
            cols[1].markdown(title_txt)
            if t["description"]:
                cols[1].caption(t["description"])
            cols[2].write(t["assigned_to"])
            cols[3].write(t["due_date"].strftime("%d-%m-%Y") if t["due_date"] else "—")
            if cols[4].button("🗑️", key=f"deltask_{t['id']}"):
                db.delete_task(t["id"])
                st.rerun()

            new_status = "Done" if done else "Open"
            if new_status != t["status"]:
                db.update_task(t["id"], status=new_status)
                st.rerun()

# ===========================================================================
# PAGINA: PIPELINE & INKOMSTEN
# ===========================================================================
elif page == "📈 Pipeline & Inkomsten":
    st.title("Pipeline & Inkomsten")
    col_income, col_pipeline = st.columns(2)

    with col_income:
        st.subheader("Inkomsten registreren")
        with st.form("add_income_form", clear_on_submit=True):
            source = st.text_input("Bron")
            amount = st.number_input("Bedrag", min_value=0.0, step=100.0)
            income_type = st.selectbox("Type", INCOME_TYPES)
            if st.form_submit_button("Inkomsten toevoegen") and source:
                db.add_income(source, amount, income_type, entered_by=current_user)
                st.success("Inkomsten geregistreerd.")
                st.rerun()

        st.markdown("**Gerealiseerde inkomsten**")
        income_rows = db.get_income()
        if income_rows:
            idf = pd.DataFrame(income_rows)[["date", "source", "type", "amount", "entered_by"]]
            idf.columns = ["Datum", "Bron", "Type", "Bedrag", "Ingevoerd door"]
            st.dataframe(idf, use_container_width=True, hide_index=True)
        else:
            st.info("Nog geen inkomsten geregistreerd.")

    with col_pipeline:
        st.subheader("Pipeline: leads & deals")
        with st.form("add_pipeline_form", clear_on_submit=True):
            company = st.text_input("Bedrijf / partij")
            p_status = st.selectbox("Fase", PIPELINE_STATUSES)
            potential_value = st.number_input("Potentiële waarde", min_value=0.0, step=500.0)
            next_action = st.text_input("Volgende actie")
            if st.form_submit_button("Pipeline-item toevoegen") and company:
                db.add_pipeline(company, p_status, potential_value, next_action, owner=current_user)
                st.success("Pipeline-item toegevoegd.")
                st.rerun()

        st.markdown("**Overzicht pipeline**")
        pipeline_rows = db.get_pipeline()
        if pipeline_rows:
            for item in pipeline_rows:
                with st.expander(f"{item['company']} — {item['status']} ({eur(item['potential_value'])})"):
                    st.caption(f"Eigenaar: {item.get('owner') or '—'}")
                    new_p_status = st.selectbox(
                        "Fase bijwerken", PIPELINE_STATUSES,
                        index=PIPELINE_STATUSES.index(item["status"]) if item["status"] in PIPELINE_STATUSES else 0,
                        key=f"pstatus_{item['id']}",
                    )
                    st.caption(f"Volgende actie: {item['next_action'] or '—'}")
                    pc1, pc2 = st.columns(2)
                    if pc1.button("Fase opslaan", key=f"save_pstatus_{item['id']}"):
                        db.update_pipeline(item["id"], status=new_p_status)
                        st.rerun()
                    if pc2.button("🗑️ Verwijderen", key=f"del_pipeline_{item['id']}"):
                        db.delete_pipeline(item["id"])
                        st.rerun()
        else:
            st.info("Nog geen pipeline-items.")

# ===========================================================================
# PAGINA: LIQUIDITEIT
# ===========================================================================
elif page == "💧 Liquiditeit":
    st.title("Liquiditeits-Cockpit")
    totals = db.get_totals()

    c1, c2, c3 = st.columns(3)
    c1.metric("Totale inkomsten (gerealiseerd)", eur(totals["total_income"]))
    c2.metric("Totale schulden (actueel, open)", eur(totals["total_debt_current"]))
    c3.metric("Netto positie", eur(totals["net_position"]))

    st.divider()
    c4, c5, c6 = st.columns(3)
    c4.metric("Schulden — oorspronkelijke hoofdsom", eur(totals["total_debt_original"]))
    c5.metric("Pipeline-potentieel (nog niet gerealiseerd)", eur(totals["pipeline_potential"]))
    c6.metric("Totaal afgelost via betalingen", eur(db.get_total_paid()))

    st.divider()
    st.caption(
        "Netto positie = Totale inkomsten (totaal) − Totale schulden (actueel, status ≠ Paid). "
        "Pipeline-potentieel telt niet mee totdat een deal wordt gerealiseerd en als inkomsten wordt geregistreerd."
    )

    if totals["total_debt_original"] > 0:
        afgelost = totals["total_debt_original"] - totals["total_debt_current"]
        pct = max(0.0, min(1.0, afgelost / totals["total_debt_original"]))
        st.markdown("**Voortgang sanering (t.o.v. oorspronkelijke hoofdsom)**")
        st.progress(pct, text=f"{pct*100:.1f}% afgelost — {eur(afgelost)} van {eur(totals['total_debt_original'])}")
