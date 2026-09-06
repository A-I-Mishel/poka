"""Memory Vault regression tests (Phase 4B).

The vault reads/writes only the current user's structured memory
(structured_memory.json) plus the separate manual notes file
(memory.md). Hermetic: tmp POKA_DATA_DIR + env identity per test, no
live model calls. AppTest drives the real sidebar UI.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent  # noqa: F401  (keeps import order consistent with other UI tests)

# Bind the app's from-imports to the REAL service functions before any
# AppTest run (see the import-order note in test_force_search_flow.py).
import application.session  # noqa: F401
import services.auth  # noqa: F401
import ui.chat  # noqa: F401
import ui.components  # noqa: F401
import ui.composer  # noqa: F401
import ui.sidebar  # noqa: F401
import ui.uploads  # noqa: F401
from services import memory as mem_mod
from services.storage import UserStore
from services.timeutil import utcnow_iso
from ui.components import mem_date_label, mem_source_label, mem_type_label

APP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def vault_env(tmp_path, monkeypatch):
    """Hermetic vault: tmp data dir; caller picks the user id."""
    monkeypatch.setenv("POKA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("POKA_AUTH_MODE", raising=False)
    monkeypatch.delenv("POKA_ACCESS_TOKENS", raising=False)
    return tmp_path / "data"


def _use_user(monkeypatch, name):
    monkeypatch.setenv("POKA_USER_ID", name)
    root = str(UserStore(name).root)
    mem_mod.set_memory_dir(root)
    return root


def _seed_facts(root, facts, user_name=None):
    mem_mod.set_memory_dir(root)
    mem_mod.save_structured_memory({
        "preferences": {},
        "facts": facts,
        "past_tasks": [],
        "user_name": user_name,
    })


def _read_facts(root):
    mem_mod.set_memory_dir(root)
    return mem_mod.load_structured_memory()


def _run_app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP_PATH)
    at.run(timeout=120)
    assert not at.exception
    at.session_state.messages = []
    at.session_state.chats = []
    at.run(timeout=60)
    assert not at.exception
    return at


def _all_text(at):
    return " ".join(
        [str(m.value) for m in at.markdown]
        + [str(c.value) for c in at.caption]
    )


def _open_memory(at):
    """Navigate to the Memory workspace view (7F location)."""
    at.button(key="more-toggle").click().run(timeout=120); at.button(key="nav-memory").click().run(timeout=120)
    assert not at.exception
    return at


# -- pure label helpers ----------------------------------------------

def test_type_labels():
    assert mem_type_label({"type": "name", "value": "A"}) == "Name"
    assert mem_type_label({"type": "preference", "value": "x"}) == "Preference"
    assert mem_type_label({"type": "preference", "value": "x",
                           "polarity": "negative"}) == "Dislike"
    assert mem_type_label({"type": "project", "value": "x"}) == "Project"
    assert mem_type_label({"type": "task_pattern", "value": "x"}) == "Pattern"
    assert mem_type_label({"type": "temporary", "value": "x"}) == "Temporary"
    assert mem_type_label({"type": "weird_kind", "value": "x"}) == "Weird Kind"
    assert mem_type_label({}) == "Memory"
    assert mem_type_label(None) == "Memory"


def test_source_labels():
    assert mem_source_label({"source": "explicit"}) == "Explicit"
    assert mem_source_label({"source": "inferred"}) == "Inferred"
    assert mem_source_label({"source": "other"}) == ""
    assert mem_source_label({}) == ""
    assert mem_source_label(None) == ""


def test_date_labels():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    assert mem_date_label(now.isoformat()) == "Remembered today"
    three = (now - timedelta(days=3)).isoformat()
    assert mem_date_label(three) == "Remembered this week"
    old = (now - timedelta(days=40)).isoformat()
    assert mem_date_label(old).startswith("Remembered ")
    assert mem_date_label("") == ""
    assert mem_date_label("not-a-date") == ""
    assert mem_date_label(None) == ""


# -- vault UI ----------------------------------------------------------

def test_empty_vault_renders(vault_env, monkeypatch):
    _use_user(monkeypatch, "vault-empty")
    at = _open_memory(_run_app())
    text = _all_text(at)
    assert "No saved memories yet" in text
    assert "Remembered facts" in text
    # legacy forget controls preserved
    at.text_input(key="forget-box")
    at.button(key="forget-memory")


def test_vault_lists_facts_with_labels(vault_env, monkeypatch):
    root = _use_user(monkeypatch, "vault-facts")
    _seed_facts(root, [
        {"type": "preference", "value": "Bengali", "polarity": "positive",
         "confidence": "high", "source": "explicit",
         "date": utcnow_iso()},
        {"type": "project", "value": "Poka", "polarity": "positive",
         "confidence": "low", "source": "inferred",
         "date": "2020-01-01T00:00:00+00:00"},
    ])
    at = _open_memory(_run_app())
    text = _all_text(at)
    assert "Bengali" in text and "Poka" in text
    assert "Preference" in text and "Explicit" in text
    assert "Project" in text and "Inferred" in text
    assert "Remembered facts (2)" in text


def test_vault_delete_removes_fact(vault_env, monkeypatch):
    root = _use_user(monkeypatch, "vault-del")
    _seed_facts(root, [
        {"type": "preference", "value": "Tea", "polarity": "positive",
         "confidence": "high", "source": "explicit", "date": utcnow_iso()},
        {"type": "preference", "value": "Coffee", "polarity": "positive",
         "confidence": "low", "source": "inferred", "date": utcnow_iso()},
    ])
    at = _open_memory(_run_app())
    assert "Tea" in _all_text(at)
    at.button(key="forget-fact-0").click().run(timeout=120)
    assert not at.exception
    text = _all_text(at)
    assert "Tea" not in text
    assert "Coffee" in text
    remaining = [f["value"] for f in _read_facts(root)["facts"]]
    assert remaining == ["Coffee"]


def test_vault_surfaces_orphaned_user_name(vault_env, monkeypatch):
    root = _use_user(monkeypatch, "vault-name")
    _seed_facts(root, [], user_name="Alice")
    at = _open_memory(_run_app())
    assert "Alice" in _all_text(at)
    at.button(key="forget-fact-name").click().run(timeout=120)
    assert not at.exception
    assert "Alice" not in _all_text(at)
    assert _read_facts(root)["user_name"] is None


def test_notes_stay_separate_and_save(vault_env, monkeypatch):
    root = _use_user(monkeypatch, "vault-notes")
    _seed_facts(root, [{"type": "preference", "value": "Tea",
                        "polarity": "positive", "confidence": "high",
                        "source": "explicit", "date": utcnow_iso()}])
    UserStore("vault-notes").save_notes("NOTE-XYZ")
    at = _open_memory(_run_app())
    assert at.text_area(key="memory-box").value == "NOTE-XYZ"
    assert "Tea" in _all_text(at)
    at.text_area(key="memory-box").set_value("NOTE-NEW").run(timeout=60)
    at.button(key="save-memory").click().run(timeout=120)
    assert not at.exception
    assert UserStore("vault-notes").load_notes() == "NOTE-NEW"
    assert [f["value"] for f in _read_facts(root)["facts"]] == ["Tea"]


def test_vault_isolated_per_user(vault_env, monkeypatch):
    alice = _use_user(monkeypatch, "vault-alice")
    _seed_facts(alice, [{"type": "preference", "value": "AliceFact",
                         "polarity": "positive", "confidence": "high",
                         "source": "explicit", "date": utcnow_iso()}])
    _use_user(monkeypatch, "vault-bob")
    at = _open_memory(_run_app())
    text = _all_text(at)
    assert "AliceFact" not in text
    assert "No saved memories yet" in text


def test_malformed_memory_fails_safe(vault_env, monkeypatch):
    root = _use_user(monkeypatch, "vault-bad")
    path = os.path.join(root, "structured_memory.json")
    os.makedirs(root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not valid json")
    at = _open_memory(_run_app())
    assert "No saved memories yet" in _all_text(at)


# -- extraction semantics unchanged ------------------------------------

def test_extraction_semantics_locked():
    facts = mem_mod.extract_facts_from_message(
        "My name is Alice and I prefer tea")
    by_type = {f["type"]: f for f in facts}
    assert by_type["name"]["value"] == "Alice"
    assert by_type["name"]["source"] == "explicit"
    assert "tea" in by_type["preference"]["value"]
    assert mem_mod.extract_facts_from_message("   ") == []
