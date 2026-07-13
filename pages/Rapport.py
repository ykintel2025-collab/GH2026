"""
pages/Rapport.py
Rapportage: draai alle schulden uit met aantekeningen, communicatie, betalingen,
taken en documenten — als HTML (printen naar PDF via de browser) of als Excel.

Deze pagina staat bewust los van app.py (Streamlit multipage), zodat de
hoofdapp ongewijzigd blijft.
"""

import html as html_lib
from datetime import date, datetime
from io import BytesIO

import pandas as pd
import streamlit as st

import auth
import database as db

st.set_page_config(page_title="Rapport — Schulden", layout="wide", page_icon="📄")

current_user = auth.check_login()

with st.sidebar:
    st.write(f"Ingelogd als **{current_user}**")

st.title("📄 Rapport uitdraaien")
st.caption(
    "Volledige uitdraai van de schulden: gegevens, betalingsafspraken, incasso, "
    "alle communicatie en aantekeningen, betalingen, taken en documenten."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def eur(x):
    try:
        return f"€ {float(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "€ 0,00"


def dnl(d):
    """Datum in NL-notatie; werkt voor date, datetime en None."""
    if not d:
        return "—"
    if isinstance(d, datetime):
        d = d.date()
    try:
        return d.strftime("%d-%m-%Y")
    except AttributeError:
        return str(d)


def esc(text):
    """HTML-veilig maken; None wordt lege string, regeleindes worden <br>."""
    if text is None:
        return ""
    return html_lib.escape(str(text)).replace("\n", "<br>")


# ---------------------------------------------------------------------------
# Data ophalen (alles via de bestaande, gecachte database-functies)
# ---------------------------------------------------------------------------

all_debts = db.get_debts()
contact_logs_all = db.get_all_contact_logs()
debt_logs_all = db.get_all_debt_logs()
payments_all = db.get_all_payments()
tasks_all = db.get_tasks()
documents_all = db.get_documents()
total_paid = db.get_total_paid()

logs_by_contact = {}
for cl in contact_logs_all:
    logs_by_contact.setdefault(cl["contact_id"], []).append(cl)

logs_by_debt = {}
for dl in debt_logs_all:
    logs_by_debt.setdefault(dl["debt_id"], []).append(dl)

payments_by_debt = {}
for p in payments_all:
    payments_by_debt.setdefault(p["debt_id"], []).append(p)

tasks_by_debt = {}
for t in tasks_all:
    if t.get("related_debt_id"):
        tasks_by_debt.setdefault(t["related_debt_id"], []).append(t)

docs_by_contact = {}
for d in documents_all:
    if d.get("contact_id"):
        docs_by_contact.setdefault(d["contact_id"], []).append(d)


def merged_logs(debt):
    """Alle communicatie bij één schuld: notities op de schuld zelf (debt_logs)
    plus alle notities op het gekoppelde contact (contact_logs), nieuwste eerst."""
    items = []
    for l in logs_by_debt.get(debt["id"], []):
        items.append({"date": l["date"], "note": l.get("note"), "logged_by": l.get("logged_by")})
    for l in logs_by_contact.get(debt.get("contact_id"), []):
        items.append({"date": l["date"], "note": l.get("note"), "logged_by": l.get("logged_by")})
    items.sort(key=lambda x: (x["date"] or date.min), reverse=True)
    return items


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

fc1, fc2 = st.columns([1, 3])
status_filter = fc1.radio("Status", ["Alle", "Open", "Paid"], horizontal=True)
names = [d["creditor_name"] or "(zonder naam)" for d in all_debts]
chosen_names = fc2.multiselect(
    "Schuldeisers (leeg = allemaal)", sorted(set(names)), default=[],
)

debts = all_debts
if status_filter != "Alle":
    debts = [d for d in debts if d["status"] == status_filter]
if chosen_names:
    debts = [d for d in debts if (d["creditor_name"] or "(zonder naam)") in chosen_names]

st.caption(f"{len(debts)} schuld(en) in dit rapport.")

if not debts:
    st.info("Geen schulden binnen dit filter — pas het filter aan.")
    st.stop()

open_debts = [d for d in debts if d["status"] != "Paid"]
sum_current = sum(float(d["current_amount"] or 0) for d in open_debts)
sum_original = sum(float(d["total_amount"] or d["current_amount"] or 0) for d in debts)
n_open = len(open_debts)
n_paid = len(debts) - n_open


# ---------------------------------------------------------------------------
# HTML-rapport
# ---------------------------------------------------------------------------

REPORT_CSS = """
    * { box-sizing: border-box; }
    body { font-family: 'Segoe UI', Arial, sans-serif; color: #1a1a2e; margin: 0;
           padding: 32px; background: #fff; font-size: 13px; line-height: 1.5; }
    h1 { font-size: 24px; margin: 0 0 4px 0; }
    h2 { font-size: 17px; margin: 0 0 8px 0; }
    .sub { color: #666; margin-bottom: 24px; }
    .totals { display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 28px;
              padding: 14px 18px; background: #f4f6fa; border-radius: 8px; }
    .totals div { min-width: 150px; }
    .totals .label { font-size: 11px; text-transform: uppercase; color: #777; }
    .totals .value { font-size: 17px; font-weight: 700; }
    .debt { border: 1px solid #dde2ec; border-radius: 8px; padding: 18px 20px;
            margin-bottom: 22px; page-break-inside: avoid; }
    .debt-header { display: flex; justify-content: space-between; align-items: baseline;
                   border-bottom: 2px solid #1a1a2e; padding-bottom: 8px; margin-bottom: 12px; }
    .badge { display: inline-block; padding: 2px 10px; border-radius: 12px;
             font-size: 11px; font-weight: 700; margin-left: 8px; }
    .badge.open { background: #fdecea; color: #b3261e; }
    .badge.paid { background: #e6f4ea; color: #1e7e34; }
    table { width: 100%; border-collapse: collapse; margin: 6px 0 14px 0; }
    th { text-align: left; font-size: 11px; text-transform: uppercase; color: #777;
         border-bottom: 1px solid #dde2ec; padding: 4px 8px 4px 0; }
    td { padding: 5px 8px 5px 0; border-bottom: 1px solid #eef1f6; vertical-align: top; }
    .kv td:first-child { width: 220px; color: #666; }
    .section-title { font-size: 12px; font-weight: 700; text-transform: uppercase;
                     color: #444; margin: 14px 0 4px 0; }
    .muted { color: #999; font-style: italic; }
    .no-print { position: fixed; top: 16px; right: 16px; }
    .no-print button { background: #1a1a2e; color: #fff; border: 0; padding: 10px 18px;
                       border-radius: 6px; font-size: 14px; cursor: pointer; }
    @media print {
        .no-print { display: none; }
        body { padding: 0; }
        .debt { border: 1px solid #ccc; }
    }
"""


def build_html(debts_list):
    now_txt = datetime.now().strftime("%d-%m-%Y %H:%M")
    filter_txt = status_filter if status_filter != "Alle" else "alle statussen"

    parts = []
    parts.append("<!DOCTYPE html><html lang='nl'><head><meta charset='utf-8'>")
    parts.append("<title>Schuldenrapport</title>")
    parts.append(f"<style>{REPORT_CSS}</style></head><body>")
    parts.append("<div class='no-print'><button onclick='window.print()'>🖨️ Print / opslaan als PDF</button></div>")
    parts.append("<h1>Schuldenrapport</h1>")
    parts.append(
        f"<div class='sub'>Uitgedraaid op {now_txt} door {esc(current_user)} · "
        f"filter: {esc(filter_txt)} · {len(debts_list)} schuld(en)</div>"
    )

    parts.append("<div class='totals'>")
    parts.append(f"<div><div class='label'>Openstaand totaal</div><div class='value'>{eur(sum_current)}</div></div>")
    parts.append(f"<div><div class='label'>Oorspronkelijke hoofdsom</div><div class='value'>{eur(sum_original)}</div></div>")
    parts.append(f"<div><div class='label'>Totaal afgelost (alle schulden)</div><div class='value'>{eur(total_paid)}</div></div>")
    parts.append(f"<div><div class='label'>Open / betaald</div><div class='value'>{n_open} open · {n_paid} betaald</div></div>")
    parts.append("</div>")

    for d in debts_list:
        status_cls = "paid" if d["status"] == "Paid" else "open"
        parts.append("<div class='debt'>")
        parts.append("<div class='debt-header'>")
        parts.append(
            f"<h2>{esc(d['creditor_name'])} "
            f"<span class='badge {status_cls}'>{esc(d['status'])}</span> "
            f"<span class='badge' style='background:#eef1f6;color:#444;'>prioriteit {esc(d.get('priority') or '—')}</span></h2>"
        )
        parts.append(f"<div><strong>{eur(d['current_amount'])}</strong> openstaand</div>")
        parts.append("</div>")

        # -- Kerngegevens
        adres = " ".join(x for x in [d.get("address"), d.get("postal_code"), d.get("city")] if x)
        parts.append("<table class='kv'>")
        rows = [
            ("Oorspronkelijke hoofdsom", eur(d["total_amount"]) if d.get("total_amount") else "—"),
            ("Actueel openstaand", eur(d["current_amount"])),
            ("Laatste contact", dnl(d.get("last_contact"))),
            ("Adres", esc(adres) or "—"),
            ("Telefoon", esc(d.get("phone")) or "—"),
            ("E-mail", esc(d.get("email")) or "—"),
            ("Betalingsafspraak", esc(d.get("payment_agreement")) or "—"),
            ("Volgende betaaldatum", dnl(d.get("next_payment_date"))),
        ]
        if d.get("repayment_amount"):
            rows.append(("Afgesproken aflossing", f"{eur(d['repayment_amount'])} ({esc(d.get('repayment_frequency') or 'Eenmalig')})"))
        if d.get("has_collector"):
            incasso = ", ".join(x for x in [
                esc(d.get("collector_name")),
                f"dossier {esc(d['collector_case_number'])}" if d.get("collector_case_number") else "",
                esc(d.get("collector_contact_person")),
                esc(d.get("collector_phone")),
                esc(d.get("collector_email")),
            ] if x)
            rows.append(("Incasso/deurwaarder", incasso or "ja"))
            if d.get("collector_notes"):
                rows.append(("Afspraken met incasso", esc(d.get("collector_notes"))))
        for label, value in rows:
            parts.append(f"<tr><td>{label}</td><td>{value}</td></tr>")
        parts.append("</table>")

        # -- Communicatie & aantekeningen
        logs = merged_logs(d)
        parts.append("<div class='section-title'>📝 Communicatie &amp; aantekeningen</div>")
        if logs:
            parts.append("<table><tr><th style='width:90px;'>Datum</th><th>Notitie</th><th style='width:90px;'>Door</th></tr>")
            for l in logs:
                parts.append(
                    f"<tr><td>{dnl(l['date'])}</td><td>{esc(l['note'])}</td><td>{esc(l.get('logged_by')) or '—'}</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<div class='muted'>Geen notities gelogd.</div>")

        # -- Betalingen
        pays = payments_by_debt.get(d["id"], [])
        parts.append("<div class='section-title'>💶 Betalingen</div>")
        if pays:
            parts.append("<table><tr><th style='width:90px;'>Datum</th><th>Bedrag</th><th style='width:90px;'>Door</th></tr>")
            for p in pays:
                parts.append(f"<tr><td>{dnl(p['date'])}</td><td>{eur(p['amount'])}</td><td>{esc(p.get('logged_by')) or '—'}</td></tr>")
            som = sum(float(p["amount"] or 0) for p in pays)
            parts.append(f"<tr><td></td><td><strong>Totaal: {eur(som)}</strong></td><td></td></tr>")
            parts.append("</table>")
        else:
            parts.append("<div class='muted'>Geen betalingen geregistreerd.</div>")

        # -- Taken
        dtasks = tasks_by_debt.get(d["id"], [])
        parts.append("<div class='section-title'>✅ Taken</div>")
        if dtasks:
            parts.append("<table><tr><th style='width:90px;'>Status</th><th>Taak</th><th style='width:110px;'>Wie</th><th style='width:90px;'>Deadline</th></tr>")
            for t in dtasks:
                icon = "✅" if t["status"] == "Done" else "⬜"
                parts.append(
                    f"<tr><td>{icon} {esc(t['status'])}</td><td>{esc(t['title'])}"
                    + (f"<br><span class='muted'>{esc(t['description'])}</span>" if t.get("description") else "")
                    + f"</td><td>{esc(t.get('assigned_to')) or '—'}</td><td>{dnl(t.get('due_date'))}</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<div class='muted'>Geen taken gekoppeld.</div>")

        # -- Documenten
        ddocs = docs_by_contact.get(d.get("contact_id"), [])
        parts.append("<div class='section-title'>📎 Documenten</div>")
        if ddocs:
            parts.append("<table><tr><th>Bestand</th><th style='width:110px;'>Geüpload</th><th style='width:110px;'>Door</th><th>Notitie</th></tr>")
            for doc in ddocs:
                parts.append(
                    f"<tr><td>{esc(doc['filename'])}</td><td>{dnl(doc.get('uploaded_at'))}</td>"
                    f"<td>{esc(doc.get('uploaded_by')) or '—'}</td><td>{esc(doc.get('notes')) or ''}</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<div class='muted'>Geen documenten.</div>")

        parts.append("</div>")  # .debt

    parts.append("</body></html>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Excel-rapport
# ---------------------------------------------------------------------------

def build_excel(debts_list):
    debt_ids = {d["id"] for d in debts_list}
    contact_ids = {d.get("contact_id") for d in debts_list if d.get("contact_id")}
    name_by_debt = {d["id"]: d["creditor_name"] for d in debts_list}
    name_by_contact = {d.get("contact_id"): d["creditor_name"] for d in debts_list if d.get("contact_id")}

    df_debts = pd.DataFrame([
        {
            "Schuldeiser": d["creditor_name"],
            "Status": d["status"],
            "Prioriteit": d.get("priority"),
            "Hoofdsom oorspronkelijk": float(d["total_amount"]) if d.get("total_amount") else None,
            "Actueel openstaand": float(d["current_amount"] or 0),
            "Laatste contact": dnl(d.get("last_contact")),
            "Betalingsafspraak": d.get("payment_agreement"),
            "Volgende betaaldatum": dnl(d.get("next_payment_date")),
            "Aflossing per keer": float(d["repayment_amount"]) if d.get("repayment_amount") else None,
            "Aflossingsfrequentie": d.get("repayment_frequency"),
            "Adres": d.get("address"),
            "Postcode": d.get("postal_code"),
            "Plaats": d.get("city"),
            "Telefoon": d.get("phone"),
            "E-mail": d.get("email"),
            "Incasso": "Ja" if d.get("has_collector") else "Nee",
            "Incassobureau": d.get("collector_name"),
            "Dossiernummer": d.get("collector_case_number"),
            "Incasso contactpersoon": d.get("collector_contact_person"),
            "Incasso telefoon": d.get("collector_phone"),
            "Incasso e-mail": d.get("collector_email"),
            "Incasso afspraken": d.get("collector_notes"),
        }
        for d in debts_list
    ])

    comm_rows = []
    for d in debts_list:
        for l in merged_logs(d):
            comm_rows.append({
                "Schuldeiser": d["creditor_name"],
                "Datum": dnl(l["date"]),
                "Notitie": l["note"],
                "Door": l.get("logged_by"),
            })
    df_comm = pd.DataFrame(comm_rows) if comm_rows else pd.DataFrame(
        columns=["Schuldeiser", "Datum", "Notitie", "Door"])

    df_pay = pd.DataFrame([
        {
            "Schuldeiser": name_by_debt.get(p["debt_id"]),
            "Datum": dnl(p["date"]),
            "Bedrag": float(p["amount"] or 0),
            "Door": p.get("logged_by"),
        }
        for p in payments_all if p["debt_id"] in debt_ids
    ]) if payments_all else pd.DataFrame(columns=["Schuldeiser", "Datum", "Bedrag", "Door"])
    if df_pay.empty:
        df_pay = pd.DataFrame(columns=["Schuldeiser", "Datum", "Bedrag", "Door"])

    df_tasks = pd.DataFrame([
        {
            "Schuldeiser": name_by_debt.get(t["related_debt_id"]),
            "Taak": t["title"],
            "Toelichting": t.get("description"),
            "Notities": t.get("notes"),
            "Status": t["status"],
            "Wie": t.get("assigned_to"),
            "Deadline": dnl(t.get("due_date")),
        }
        for t in tasks_all if t.get("related_debt_id") in debt_ids
    ])
    if df_tasks.empty:
        df_tasks = pd.DataFrame(columns=["Schuldeiser", "Taak", "Toelichting", "Notities", "Status", "Wie", "Deadline"])

    df_docs = pd.DataFrame([
        {
            "Schuldeiser": name_by_contact.get(doc.get("contact_id")),
            "Bestand": doc["filename"],
            "Geüpload": dnl(doc.get("uploaded_at")),
            "Door": doc.get("uploaded_by"),
            "Notitie": doc.get("notes"),
        }
        for doc in documents_all if doc.get("contact_id") in contact_ids
    ])
    if df_docs.empty:
        df_docs = pd.DataFrame(columns=["Schuldeiser", "Bestand", "Geüpload", "Door", "Notitie"])

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_debts.to_excel(writer, sheet_name="Schulden", index=False)
        df_comm.to_excel(writer, sheet_name="Communicatie", index=False)
        df_pay.to_excel(writer, sheet_name="Betalingen", index=False)
        df_tasks.to_excel(writer, sheet_name="Taken", index=False)
        df_docs.to_excel(writer, sheet_name="Documenten", index=False)
        # Kolombreedtes een beetje leesbaar maken
        for sheet in writer.sheets.values():
            for col_cells in sheet.columns:
                width = max((len(str(c.value)) for c in col_cells if c.value is not None), default=10)
                sheet.column_dimensions[col_cells[0].column_letter].width = min(max(width + 2, 12), 60)
    buf.seek(0)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Download-knoppen
# ---------------------------------------------------------------------------

vandaag = date.today().strftime("%Y-%m-%d")

col_html, col_xlsx = st.columns(2)

with col_html:
    st.markdown("**📄 Rapport (HTML → PDF)**")
    st.caption("Open het bestand in je browser en klik op '🖨️ Print / opslaan als PDF'.")
    st.download_button(
        "⬇️ Download rapport (HTML)",
        data=build_html(debts),
        file_name=f"schuldenrapport_{vandaag}.html",
        mime="text/html",
        use_container_width=True,
    )

with col_xlsx:
    st.markdown("**📊 Excel-export**")
    st.caption("Tabbladen: Schulden, Communicatie, Betalingen, Taken, Documenten.")
    st.download_button(
        "⬇️ Download Excel (.xlsx)",
        data=build_excel(debts),
        file_name=f"schuldenrapport_{vandaag}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
