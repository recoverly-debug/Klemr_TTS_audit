"""Klemr Audit Engine — Streamlit review UI (wired in Step 6).

This is a placeholder. The real UI is a THIN shell that imports the engine modules
(`klemr.*`) and writes every verification decision through the engine to the SQLite
evidence ledger — it will contain no business logic of its own.

Run (once built):  streamlit run app.py
"""
from __future__ import annotations

try:
    import streamlit as st
except ModuleNotFoundError:  # the `ui` optional-dependency group isn't installed yet
    raise SystemExit(
        "Streamlit isn't installed. Install the UI extra:  uv sync --extra ui\n"
        "The review UI is wired in Step 6; the engine (klemr.*) and its tests run "
        "without it."
    )

from klemr import __version__

st.set_page_config(page_title="Klemr Audit Engine", layout="wide")
st.title("Klemr Audit Engine")
st.caption(f"v{__version__} · RAF auto-cancellation exemption (Leakage 1a)")
st.info("UI is wired in Step 6. The deterministic engine lives in `klemr/`.")
