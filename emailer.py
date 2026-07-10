"""
emailer.py
Verstuurt e-mails via het Gmail-account dat is gekoppeld in st.secrets.
Vereist een Gmail 'App-wachtwoord' (geen normaal Gmail-wachtwoord, zie instructies).
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import streamlit as st


def send_email(to_address, subject, body, attachments=None):
    """Verstuurt een e-mail. 'attachments' is optioneel: een lijst van (bestandsnaam, bytes)-tuples.
    Retourneert (succes: bool, foutmelding: str|None)."""
    if not to_address:
        return False, "Geen e-mailadres opgegeven."

    try:
        gmail_address = st.secrets["gmail"]["address"]
        app_password = st.secrets["gmail"]["app_password"]
    except Exception:
        return False, "Gmail-koppeling is nog niet ingesteld (ontbreekt in Secrets)."

    msg = MIMEMultipart()
    msg["From"] = gmail_address
    msg["To"] = to_address
    msg["Subject"] = subject or "(geen onderwerp)"
    msg.attach(MIMEText(body or "", "plain"))

    for filename, file_bytes in (attachments or []):
        try:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(file_bytes)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
            msg.attach(part)
        except Exception:
            pass  # een mislukte bijlage mag het versturen van de rest niet blokkeren

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_address, app_password)
            server.sendmail(gmail_address, to_address, msg.as_string())
        return True, None
    except smtplib.SMTPAuthenticationError:
        return False, "Inloggen bij Gmail is mislukt — klopt het App-wachtwoord nog?"
    except Exception as e:
        return False, str(e)
