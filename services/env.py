"""Shared safe environment builder for subprocess children.

Both `services.coderun` and `services.mcp` spawn subprocesses with
minimal env to avoid leaking secrets (API keys, tokens) to third-party
binaries. Single source of truth for allowed keys and secret hints.
"""

from __future__ import annotations

import os
from typing import Dict

_SECRET_HINTS = ("key", "token", "secret", "password", "passwd", "authorization", "credential")

# Minimal non-secret vars a stdio child needs to spawn. Everything else — provider
# API keys, PLUTO_ACCESS_TOKENS, GOOGLE_REFRESH_TOKEN — must NOT leak.
_SAFE_ENV_KEYS = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    "PROCESSOR_ARCHITECTURE",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LANGUAGE",
    "TZ",
    "TERM",
    "LOGNAME",
    "USER",
    "USERNAME",
    "SHELL",
    "COMSPEC",
    "PYTHONIOENCODING",
    "NODE_ENV",
    "NO_COLOR",
)


def base_env() -> Dict[str, str]:
    """Small safe base env for stdio children (never the full os.environ)."""
    base: Dict[str, str] = {}
    for key in _SAFE_ENV_KEYS:
        value = os.environ.get(key)
        if value is None:
            continue
        if value.startswith("()"):
            # Skip exported shell functions (security risk).
            continue
        base[key] = value
    return base


def safe_env() -> Dict[str, str]:
    """Minimal env for child processes with secret-like keys stripped."""
    env = base_env()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("NO_COLOR", "1")
    for k in list(env.keys()):
        if any(h in k.lower() for h in _SECRET_HINTS):
            env.pop(k, None)
    return env
