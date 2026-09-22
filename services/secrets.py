"""Centralized secret/config-value reading.

Single seam for every credential lookup in the app (provider API keys,
PLUTO_ACCESS_TOKENS, PLUTO_AUTH_MODE, PLUTO_USER_ID): environment variables
/ .env.

Do NOT duplicate this logic: services.auth, services.identity, and
config all read through get_secret() so a secret configured in exactly
one place is honored everywhere. A missing secret in both places yields
the default (never an exception, never a bypass).

Raw secret values are never logged; callers must treat them as opaque.
"""

import os
from typing import Optional


_PLACEHOLDERS = frozenset({
    "your_gemini_key_here",
    "your_groq_key_here",
    "your_openrouter_key_here",
    "your_mistral_key_here",
    "your_cohere_key_here",
    "your_client_id.apps.googleusercontent.com",
})

def is_placeholder(value: Optional[str]) -> bool:
    """True if value is missing or an unreplaced placeholder."""
    if not value:
        return True
    v = value.strip()
    return not v or v in _PLACEHOLDERS or v.startswith("your_")

def get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Return a secret from the environment, else default.

    Unreplaced placeholder values (your_* / example hosts) never count
    as configured: they resolve to default so callers cannot mistake
    a template .env for real credentials.

    Args:
        name: Secret name, e.g. "GEMINI_API_KEY" or "PLUTO_ACCESS_TOKENS".
        default: Value when the secret is set nowhere (or placeholder).

    Returns:
        The secret value, or default if not set anywhere.
    """
    val = os.getenv(name, default)
    if val is not None and val != default and is_placeholder(val):
        return default
    return val

def validate_secrets() -> list[str]:
    """Return warnings for missing/placeholder secrets (never logs values).

    Note: this module is the only place allowed direct os.getenv —
    every other module must read through get_secret() so placeholder
    filtering cannot be bypassed.
    """
    warnings: list[str] = []
    mode = os.getenv("PLUTO_AUTH_MODE", "open") or "open"
    if mode.strip().lower() == "private" and not os.getenv("PLUTO_ACCESS_TOKENS"):
        warnings.append("PLUTO_AUTH_MODE=private but PLUTO_ACCESS_TOKENS is empty — no one can log in")
    # warn if no LLM tier is configured at all (keys counted only when
    # a live lane reads them — retired lanes don't count).
    has_any = False
    for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
              "COHERE_API_KEY"):
        raw = os.getenv(k)
        if raw and not is_placeholder(raw):
            has_any = True
            break
    if not has_any:
        warnings.append("No LLM API key configured — /api/health will show empty tiers")
    return warnings
