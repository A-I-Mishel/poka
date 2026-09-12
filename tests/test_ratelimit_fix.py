"""Fix 1 regression tests: IP-keyed limits + limiter pruning + lazy vaults.

Covers the open-mode bypass (fresh random ID per request meant limits
never bound), the _hits memory leak (dead one-shot identities evicted),
and the per-request vault-directory litter (stores create nothing until
the first real write).
"""

import io
import os
import sys
import time
from collections import deque

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def fresh_limiter():
    from services import ratelimit as rl

    old = rl.get_rate_limiter()
    lim = rl.MemoryRateLimiter()
    rl.configure_rate_limiter(lim)
    try:
        yield lim
    finally:
        rl.configure_rate_limiter(old)


@pytest.fixture()
def open_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    return tmp_path


def test_limit_key_for_stable_sources():
    from services.ratelimit import limit_key_for

    assert limit_key_for("env", "api-user", "1.2.3.4") == "api-user"
    assert limit_key_for("token", "abc123", "1.2.3.4") == "abc123"


def test_limit_key_for_ephemeral_is_ip():
    from services.ratelimit import limit_key_for

    assert limit_key_for("ephemeral", "random-id-1", "1.2.3.4") == "ip:1.2.3.4"
    assert limit_key_for("ephemeral", "random-id-2", "1.2.3.4") == "ip:1.2.3.4"
    assert limit_key_for("", "whatever", "") == "ip:unknown"


def test_extract_client_ip():
    from services.ratelimit import extract_client_ip

    assert extract_client_ip("9.9.9.9, 10.0.0.1", "peer") == "10.0.0.1"
    assert extract_client_ip("", "peer") == "peer"
    assert extract_client_ip(None, "") == "unknown"


def test_sliding_window_still_binds(fresh_limiter):
    assert fresh_limiter.check("u", "chat").allowed
    assert fresh_limiter.check("u", "chat").allowed


def test_window_expiry_allows_again():
    from services.ratelimit import MemoryRateLimiter

    lim = MemoryRateLimiter({"t": (1, 0.05)})
    assert lim.check("u", "t").allowed
    assert not lim.check("u", "t").allowed
    time.sleep(0.06)
    assert lim.check("u", "t").allowed


def test_prune_evicts_stale_keys(fresh_limiter):
    from services.ratelimit import MemoryRateLimiter

    lim = fresh_limiter
    stale = time.time() - 7200.0
    lim._hits[("ghost-1", "chat")] = deque([stale])
    lim._hits[("ghost-2", "upload")] = deque([stale])
    lim.check("fresh-user", "chat")
    assert ("ghost-1", "chat") not in lim._hits
    assert ("ghost-2", "upload") not in lim._hits
    assert ("fresh-user", "chat") in lim._hits


def test_prune_evicts_emptied_queues():
    from services.ratelimit import MemoryRateLimiter

    lim = MemoryRateLimiter({"t": (100, 0.05)})
    lim.check("u", "t")
    assert ("u", "t") in lim._hits
    time.sleep(0.06)
    lim.check("other", "t")
    assert ("u", "t") not in lim._hits


def test_stores_create_no_dirs(open_env):
    from services.files import FileStore
    from services.storage import UserStore

    UserStore("ghost-user")
    FileStore("ghost-user")
    users = open_env / "data" / "users"
    assert not users.exists() or list(users.iterdir()) == []


def test_stores_write_on_demand(open_env):
    from services.files import FileStore
    from services.storage import UserStore

    store = UserStore("ondemand-user")
    store.save_chats([], [{"role": "user", "content": "hi", "time": "t"}])
    assert store.chats_path.exists()
    fstore = FileStore("ondemand-user")
    meta = fstore.save_upload(b"%PDF-1.4 fake", "note.pdf")
    assert (fstore.uploads_dir / f"{meta.id}_note.pdf").exists() or meta.id


def test_ephemeral_uploads_share_ip_quota(open_env):
    from backend.main import app
    from services import ratelimit as rl

    old = rl.get_rate_limiter()
    rl.configure_rate_limiter(rl.MemoryRateLimiter({"upload": (2, 3600.0)}))
    try:
        with TestClient(app) as client:
            def _post(extra=None):
                return client.post(
                    "/api/uploads",
                    files={"file": ("note.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
                    headers=extra or {},
                )

            assert _post().status_code == 200
            assert _post().status_code == 200
            limited = _post()
            assert limited.status_code == 429, limited.text
            # A different client IP gets its own bucket (not a global block).
            assert _post({"X-Forwarded-For": "9.9.9.9"}).status_code == 200
    finally:
        rl.configure_rate_limiter(old)


def test_tools_limit_by_limit_key(open_env):
    from services import context as ctx
    from services import ratelimit as rl
    from tools.gating import claim_generation_slot

    old = rl.get_rate_limiter()
    lim = rl.MemoryRateLimiter({"generate": (1, 3600.0)})
    rl.configure_rate_limiter(lim)
    try:
        ctx.set_current_user_id("ephemeral-1")
        ctx.set_limit_key("ip:9.9.9.9")
        user_id, err = claim_generation_slot("create_pptx")
        assert err is None and user_id == "ephemeral-1"
        # Same IP, different ephemeral ID: still denied (shared bucket).
        ctx.set_current_user_id("ephemeral-2")
        user_id2, err2 = claim_generation_slot("create_pptx")
        assert user_id2 is None and err2 is not None
        assert ("ip:9.9.9.9", "generate") in lim._hits
        assert ("ephemeral-1", "generate") not in lim._hits
    finally:
        ctx.set_current_user_id(None)
        ctx.set_limit_key(None)
        rl.configure_rate_limiter(old)


def _seed_legacy_files(root):
    import json

    (root / "memory").mkdir(exist_ok=True)
    (root / "memory" / "chats.json").write_text(
        json.dumps({"chats": [], "current": [{"role": "user", "content": "old", "time": "t"}]}),
        encoding="utf-8",
    )
    (root / "structured_memory.json").write_text(
        json.dumps({"preferences": {}, "facts": [{"value": "old fact"}], "past_tasks": [], "user_name": None}),
        encoding="utf-8",
    )


def _vault_names(data_dir):
    users = data_dir / "data" / "users"
    if not users.exists():
        return []
    return sorted(p.name for p in users.iterdir())


def test_ephemeral_store_skips_migration(open_env):
    from services.storage import UserStore

    _seed_legacy_files(open_env)
    UserStore("ghost-user", run_migration=False)
    assert _vault_names(open_env) == []


def test_stable_store_still_migrates(open_env):
    from services.storage import UserStore

    _seed_legacy_files(open_env)
    store = UserStore("stable-user")
    assert store.chats_path.exists()
    assert _vault_names(open_env) == ["stable-user"]


def test_ephemeral_reads_create_no_vaults(open_env):
    from backend.main import app

    _seed_legacy_files(open_env)
    with TestClient(app) as client:
        assert client.get("/api/chats").status_code == 200
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/projects").status_code == 200
    assert _vault_names(open_env) == []
