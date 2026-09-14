"""Root pytest fixtures for the Pluto hermetic suite.

Deliberately minimal: test modules self-isolate today (per-file sys.path
inserts, tmp cwd, stubbed models). This file only guarantees the repo
root is importable for new tests and offers one opt-in fixture; nothing
here runs automatically against existing tests.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))


@pytest.fixture()
def pluto_env(tmp_path, monkeypatch):
    """Isolated data dir + stable open-mode identity (opt-in)."""
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "test-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path
