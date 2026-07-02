"""
app.py
Streamlit UI voor het High-Performance Asset Management dashboard.
Draaien met: streamlit run app.py
Vereist st.secrets["DB_URL"] en st.secrets["credentials"] (zie secrets.toml.example).
"""

import streamlit as st
import pandas as pd
import database as db
import auth

st.set_page_config(page_title="Asset Management Dashboard", layout="wide")

# --- Login ---------------------------------------------------------------
current_user = auth.check_login()
auth.logout_button()

# --- Database init (idempotent, veilig om elke keer te draaien) ----------
db.init_db()

st.title("High-Performance Asset Management")

tab_debts, tab_pipeline, tab_liquidity = st.tabs(
    ["📋 Schulden Overzicht", "📈 Pipeline & Inkomsten", "💧 Liquiditeits-Cockpit"]
)

PRIORITIES = ["A", "B", "C"]
STATUSES = ["Open", "Paid"]
PIPELINE_STATUSES = ["Lead", "Pitch", "Deal"]
INCOME_TYPES = ["Private", "Ambassadorship"]


def eur(x):
    try:
        return f"€ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "€ 0,00"


# ---------------------------------------------------------------------------
# TAB 1: SCHULDEN OVERZICHT
# ---------------------------------------------------------------------------
with tab_debts:
    st.subheader("Nieuwe schuld toevoegen")
    with st.form("add_debt_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        creditor_name = c1.text_input("Schuldeiser")
        total_amount = c2.number_input("Hoofdsom oorspronkelijk", min_value=0.0, step=100.0)
        current_amount = c3.number_input("Actueel bedrag", min_value=0.0, step=100.0)
        priority = c4.selectbox("Prioriteit", PRIORITIES)
        submitted = st.form_submit_button("Schuld toevoegen")
        if submitted and creditor_name:
            db.add_debt(creditor_name, total_amount, current_amount, priority)
            st.success(f"Schuld bij {creditor_name} toegevoegd.")
            st.rerun()

    st.divider()
    st.subheader("Openstaande & afgeronde schulden")

    status_filter = st.radio("Filter status", ["Alle", "Open", "Paid"], horizontal=True)
    debts = db.get_debts(status=None if status_filter == "Alle" else status_filter)

    if not debts:
        st.info("Nog geen schulden geregistreerd.")
    else:
        df = pd.DataFrame(debts)[
            ["id", "creditor_name", "priority", "total_amount", "current_amount", "status", "last_contact"]
        ]
        df.columns = ["ID", "Schuldeiser", "Prio", "Hoofdsom", "Actueel", "Status", "Laatste contact"]
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Detail & communicatielog per schuld")
        for debt in debts:
            with st.expander(
                f"{debt['creditor_name']} — {eur(debt['current_amount'])} (Prio {debt['priority']}, {debt['status']})"
            ):
                dc1, dc2, dc3 = st.columns(3)

                with dc1:
                    new_amount = st.number_input(
                        "Actueel bedrag bijwerken",
                        min_value=0.0,
                        value=float(debt["current_amount"]),
                        step=50.0,
                        key=f"amt_{debt['id']}",
                    )
                    if st.button("Bedrag opslaan", key=f"save_amt_{debt['id']}"):
                        db.update_debt(debt["id"], current_amount=new_amount)
                        st.rerun()

                with dc2:
                    new_status = st.selectbox(
                        "Status",
                        STATUSES,
                        index=STATUSES.index(debt["status"]) if debt["status"] in STATUSES else 0,
                        key=f"status_{debt['id']}",
                    )
                    if st.button("Status opslaan", key=f"save_status_{debt['id']}"):
                        db.update_debt(debt["id"], status=new_status)
                        st.rerun()

                with dc3:
                    if st.button("🗑️ Schuld verwijderen", key=f"del_{debt['id']}"):
                        db.delete_debt(debt["id"])
                        st.rerun()

                st.markdown("**Communicatie-log**")
                logs = db.get_debt_logs(debt["id"])
                if logs:
                    for log in logs:
                        wie = f" — *{log['logged_by']}*" if log.get("logged_by") else ""
                        st.write(f"- `{log['date']}` {log['note']}{wie}")
                else:
                    st.caption("Nog geen notities.")

                with st.form(f"log_form_{debt['id']}", clear_on_submit=True):
                    note = st.text_input("Nieuwe notitie", key=f"note_{debt['id']}")
                    log_submit = st.form_submit_button("Notitie loggen")
                    if log_submit and note:
                        db.add_debt_log(debt["id"], note, logged_by=current_user)
                        st.rerun()

# ---------------------------------------------------------------------------
# TAB 2: PIPELINE & INKOMSTEN
# ---------------------------------------------------------------------------
with tab_pipeline:
    col_income, col_pipeline = st.columns(2)

    with col_income:
        st.subheader("Inkomsten registreren")
        with st.form("add_income_form", clear_on_submit=True):
            source = st.text_input("Bron")
            amount = st.number_input("Bedrag", min_value=0.0, step=100.0)
            income_type = st.selectbox("Type", INCOME_TYPES)
            income_submit = st.form_submit_button("Inkomsten toevoegen")
            if income_submit and source:
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
            pipeline_submit = st.form_submit_button("Pipeline-item toevoegen")
            if pipeline_submit and company:
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
                        "Fase bijwerken",
                        PIPELINE_STATUSES,
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

# ---------------------------------------------------------------------------
# TAB 3: LIQUIDITEITS-COCKPIT
# ---------------------------------------------------------------------------
with tab_liquidity:
    st.subheader("Liquiditeitspositie")
    totals = db.get_totals()

    c1, c2, c3 = st.columns(3)
    c1.metric("Totale inkomsten (gerealiseerd)", eur(totals["total_income"]))
    c2.metric("Totale schulden (actueel, open)", eur(totals["total_debt_current"]))
    c3.metric("Netto positie", eur(totals["net_position"]))

    st.divider()
    c4, c5 = st.columns(2)
    c4.metric("Schulden — oorspronkelijke hoofdsom (totaal)", eur(totals["total_debt_original"]))
    c5.metric("Pipeline-potentieel (nog niet gerealiseerd)", eur(totals["pipeline_potential"]))

    st.divider()
    st.caption(
        "Netto positie = Totale inkomsten (totaal) − Totale schulden (actueel, status ≠ Paid). "
        "Pipeline-potentieel telt niet mee in de netto positie totdat een deal wordt gerealiseerd "
        "en als inkomsten wordt geregistreerd."
    )

    if totals["total_debt_original"] > 0:
        afgelost = totals["total_debt_original"] - totals["total_debt_current"]
        pct = max(0.0, min(1.0, afgelost / totals["total_debt_original"]))
        st.markdown("**Voortgang sanering (t.o.v. oorspronkelijke hoofdsom)**")
        st.progress(pct, text=f"{pct*100:.1f}% afgelost — {eur(afgelost)} van {eur(totals['total_debt_original'])}")
