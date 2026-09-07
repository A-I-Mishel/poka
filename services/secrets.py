"""Centralized secret/config-value reading.

Single seam for every credential lookup in the app (provider API keys,
POKA_ACCESS_TOKENS, POKA_AUTH_MODE, POKA_USER_ID): environment variables
/ .env.

Do NOT duplicate this logic: services.auth, services.identity, and
config all read through get_secret() so a secret configured in exactly
one place is honored everywhere. A missing secret in both places yields
the default (never an exception, never a bypass).

Raw secret values are never logged; callers must treat them as opaque.
"""

import os
from typing import Optional


def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Return a secret from the environment, else default.

    Args:
        name: Secret name, e.g. "GEMINI_API_KEY" or "POKA_ACCESS_TOKENS".
        default: Value when the secret is set nowhere.

    Returns:
        The secret value, or default if not set anywhere.
    """
    return os.getenv(name, default)
