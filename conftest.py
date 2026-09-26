"""Root pytest fixtures for the Pluto hermetic suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))


@pytest.fixture(autouse=True)
def _pluto_hermetic(tmp_path, monkeypatch):
    """Auto-reset global caches between tests (prevents cross-test bleed)."""
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    # Hermetic against ambient local .env (e.g. a developer's
    # PLUTO_AUTH_MODE=private / PLUTO_USER_ID / SNAPSHOT_ENABLED=false):
    # the suite assumes defaults unless a test sets its own values.
    for _var in ("PLUTO_AUTH_MODE", "PLUTO_USER_ID",
                 "PLUTO_FRONTEND_ORIGIN", "SNAPSHOT_ENABLED",
                 "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
                 "COHERE_API_KEY", "PLUTO_HEALTH_PROBE", "PLUTO_DOTENV",
                 "PLUTO_DOTENV_PATH"):
        monkeypatch.delenv(_var, raising=False)
    monkeypatch.setenv("PLUTO_HEALTH_PROBE", "0")
    monkeypatch.chdir(tmp_path)
    yield
    try:
        from backend.deps import clear_all_store_caches

        clear_all_store_caches()
    except Exception:  # noqa: S110 -- best-effort test isolation
        pass
    for mod_name, attr in [
        ("agent.cascade", "reset_tier_state"),
        ("agent.answer", "_clear_summary_cache"),
        ("agent.router", "_reset_fallthrough_stats"),
        ("config", "_clear_client_cache"),
    ]:
        try:
            mod = sys.modules.get(mod_name)
            if mod is None:
                __import__(mod_name)
                mod = sys.modules.get(mod_name)
            fn = getattr(mod, attr, None)
            if callable(fn):
                try:
                    fn()
                except TypeError:
                    pass
        except Exception:  # noqa: S110 -- best-effort test isolation
            pass
    try:
        from services.ratelimit import configure_rate_limiter, MemoryRateLimiter

        configure_rate_limiter(MemoryRateLimiter())
    except Exception:  # noqa: S110 -- best-effort test isolation
        pass


@pytest.fixture()
def pluto_env(tmp_path, monkeypatch):
    """Isolated data dir + stable open-mode identity (opt-in)."""
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "test-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path
