"""Centralized secret/config-value reading.

Single seam for every credential lookup in the app (provider API keys,
POKA_ACCESS_TOKENS, POKA_AUTH_MODE, POKA_USER_ID):

1. Streamlit Secrets (Cloud deployments) first,
2. environment variables / .env second.

Do NOT duplicate this logic: services.auth, services.identity, and
config all read through get_secret() so a secret configured in exactly
one place is honored everywhere. A missing secret in both places yields
the default (never an exception, never a bypass).

Raw secret values are never logged; callers must treat them as opaque.
"""

import os
from typing import Optional


def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Return a secret from Streamlit Secrets, else env, else default.

    Args:
        name: Secret name, e.g. "GEMINI_API_KEY" or "POKA_ACCESS_TOKENS".
        default: Value when the secret is set nowhere.

    Returns:
        The secret value, or default if not set anywhere.
    """
    try:
        import streamlit as st

        # load_if_toml_exists() never raises or prints when no file exists
        # (plain st.secrets access would st.error + break set_page_config order).
        if st.secrets.load_if_toml_exists():
            val = st.secrets.get(name)
            if val:
                return str(val)
    except Exception:
        pass
    return os.getenv(name, default)
