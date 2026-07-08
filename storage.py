"""
storage.py
Praat met Supabase Storage (bestandsopslag) via de REST API.
Vereist st.secrets["SUPABASE_URL"] en st.secrets["SUPABASE_SERVICE_KEY"].
"""

import requests
import streamlit as st

BUCKET = "documenten"


def _base_url():
    return st.secrets["SUPABASE_URL"].rstrip("/") + "/storage/v1"


def _headers(content_type=None):
    key = st.secrets["SUPABASE_SERVICE_KEY"]
    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def upload_file(file_bytes, storage_path, content_type="application/octet-stream"):
    """Uploadt een bestand. Retourneert (succes: bool, foutmelding: str|None)."""
    try:
        url = f"{_base_url()}/object/{BUCKET}/{storage_path}"
        resp = requests.post(url, headers=_headers(content_type), data=file_bytes, timeout=30)
        if resp.status_code in (200, 201):
            return True, None
        return False, f"{resp.status_code}: {resp.text}"
    except Exception as e:
        return False, str(e)


def get_download_url(storage_path, expires_in=3600):
    """Vraagt een tijdelijke downloadlink op (verloopt na expires_in seconden)."""
    try:
        url = f"{_base_url()}/object/sign/{BUCKET}/{storage_path}"
        resp = requests.post(url, headers=_headers("application/json"), json={"expiresIn": expires_in}, timeout=15)
        if resp.status_code == 200:
            signed_path = resp.json().get("signedURL")
            if signed_path:
                return st.secrets["SUPABASE_URL"].rstrip("/") + "/storage/v1" + signed_path
        return None
    except Exception:
        return None


def delete_file(storage_path):
    try:
        url = f"{_base_url()}/object/{BUCKET}/{storage_path}"
        resp = requests.delete(url, headers=_headers(), timeout=15)
        return resp.status_code in (200, 204)
    except Exception:
        return False
