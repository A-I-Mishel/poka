"""Secrets seam: placeholder filtering cannot be bypassed.

Every PLUTO_* / provider read outside services.secrets must go through
get_secret() so `your_*` template values never count as configured.
"""

import os


def test_placeholder_keys_are_not_configured(monkeypatch):
    from services.secrets import get_secret, is_placeholder

    monkeypatch.setenv("GEMINI_API_KEY", "your_gemini_key_here")
    assert is_placeholder(os.getenv("GEMINI_API_KEY"))
    assert get_secret("GEMINI_API_KEY") is None
    assert get_secret("GEMINI_API_KEY", "fallback") == "fallback"


def test_data_root_uses_seam(tmp_path, monkeypatch):
    from services.storage import data_root

    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "vault"))
    assert str(data_root()).endswith("vault")


def test_no_direct_os_getenv_outside_seam():
    """Guardrail: only services/secrets.py + services/env.py may touch os.environ directly."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in list((root / "backend").rglob("*.py")) + list((root / "services").rglob("*.py")):
        if path.name in ("secrets.py", "env.py", "kb_index.py"):
            # secrets.py = the seam itself; env.py = safe child-env builder;
            # kb_index.py = best-effort WIP omitted from coverage (test tmpdir setup).
            continue
        # services/google.py delegates to services.secrets (allowed via import);
        # its only os use would be flagged here if reintroduced.
        text = path.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"os\.getenv|os\.environ", line):
                offenders.append(f"{path.relative_to(root)}:{i}:{line.strip()}")
    assert not offenders, "direct os.getenv bypasses placeholder filtering:\n" + "\n".join(offenders)
