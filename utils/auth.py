"""
Guard de autenticación para páginas individuales.

La verificación real ocurre en app.py (único punto de entrada de la
navegación). Esto es una segunda barrera por si alguna página llegara
a ejecutarse fuera de ese flujo.
"""
import streamlit as st


def require_auth():
    if not st.session_state.get("authentication_status"):
        st.error("Debes iniciar sesión para ver esta página.")
        st.stop()
