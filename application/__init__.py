"""Application layer: session state, agent calls, page-flow operations.

Sits between the UI (app.py, ui/*) and services/agent. Owns nothing
visual; operates on Streamlit session state and per-request services.
"""
