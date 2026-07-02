"""
auth.py
Simpele login voor 3 vaste gebruikers. Wachtwoorden staan in st.secrets
(dus in Streamlit Cloud -> Settings -> Secrets), nooit in de code of op GitHub.
"""

import streamlit as st


def check_login():
    """
    Toont een login-formulier tot de gebruiker is ingelogd.
    Zet bij succes st.session_state['user'] op de displaynaam.
    """
    if st.session_state.get("authenticated"):
        return st.session_state["user"]

    st.title("Inloggen")
    with st.form("login_form"):
        username = st.text_input("Gebruikersnaam").strip().lower()
        password = st.text_input("Wachtwoord", type="password")
        submitted = st.form_submit_button("Inloggen")

    if submitted:
        users = st.secrets.get("credentials", {})
        user_record = users.get(username)
        if user_record and password == user_record["password"]:
            st.session_state["authenticated"] = True
            st.session_state["user"] = user_record["name"]
            st.rerun()
        else:
            st.error("Onjuiste gebruikersnaam of wachtwoord.")

    st.stop()


def logout_button():
    with st.sidebar:
        st.write(f"Ingelogd als **{st.session_state.get('user', '')}**")
        if st.button("Uitloggen"):
            st.session_state["authenticated"] = False
            st.session_state["user"] = None
            st.rerun()
