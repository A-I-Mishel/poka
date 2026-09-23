"""Regression tests for the production audit remediation (findings 1-6).

Hermetic: tmp PLUTO_DATA_DIR, no network, no real credentials.
"""

import os
import sys
import threading
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def api_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    from backend.deps import clear_all_store_caches
    from services import kb_ingest as _kbi

    clear_all_store_caches()
    _kbi.reset_for_tests()
    yield tmp_path
    _kbi.reset_for_tests()
    clear_all_store_caches()


# ---- Finding 1: public metrics strip identity families ----

def test_public_metrics_hide_privileged_families(api_env, monkeypatch):
    # Explicit open mode, no stable identity: importing backend.main
    # runs load_dotenv(), which can restore .env values over deleted
    # vars — so pin the env AFTER the import as well.
    import backend.main as main

    monkeypatch.setenv("PLUTO_AUTH_MODE", "open")
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_METRICS_TOKEN", raising=False)
    monkeypatch.delenv("PLUTO_ACCESS_TOKENS", raising=False)
    from services import obs as _obs

    _obs.set_kb_index_size("audit-u1", 3)
    _obs.set_migration_status("audit-u1", 1)
    _obs.set_rate_limit_bucket_state("chat", "audit-id1", 1, 9, 10)

    with TestClient(main.app) as client:
        res = client.get("/api/metrics")
        assert res.status_code == 200
        assert "pluto_" in res.text  # still serves public metrics
        assert "pluto_kb_index_size" not in res.text
        assert "pluto_storage_migration_status" not in res.text
        assert "pluto_rate_limit_bucket_state" not in res.text


def test_metrics_token_unlocks_full_registry(api_env, monkeypatch):
    import backend.main as main

    monkeypatch.setenv("PLUTO_AUTH_MODE", "open")
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.setenv("PLUTO_METRICS_TOKEN", "scrape-secret")
    from services import obs as _obs

    _obs.set_rate_limit_bucket_state("chat", "audit-token-id", 2, 8, 10)

    with TestClient(main.app) as client:
        res = client.get("/api/metrics", headers={"X-Pluto-Metrics-Token": "scrape-secret"})
        assert res.status_code == 200
        assert "pluto_rate_limit_bucket_state" in res.text
        # Wrong token stays filtered.
        res2 = client.get("/api/metrics", headers={"X-Pluto-Metrics-Token": "wrong"})
        assert "pluto_rate_limit_bucket_state" not in res2.text


def test_identity_cardinality_guard_bounds_series():
    from services import obs as _obs

    seen: set = set()
    for i in range(3):
        assert _obs._admit(seen, f"id-{i}", 3) is True
    # Cap of 3: new identities refused, known ones still admitted.
    assert _obs._admit(seen, "id-new", 3) is False
    assert _obs._admit(seen, "id-0", 3) is True
    assert len(seen) == 3  # only the first 3 were tracked


# ---- Finding 2: bounded background ingest ----

def test_kb_ingest_sheds_when_saturated():
    from backend.routers import uploads as up
    from services import kb_ingest as kbi

    # Occupy every slot manually, then scheduling must shed (never block).
    assert kbi._kb_ingest_sema.acquire(blocking=False)
    assert kbi._kb_ingest_sema.acquire(blocking=False)
    try:
        assert up.schedule_kb_ingest("u", "id1", "a.txt", b"data") is False
        # Shed entries wait in the disk-backed backlog (identity only).
        assert kbi.backlog_depth() == 1
    finally:
        kbi._kb_ingest_sema.release()
        kbi._kb_ingest_sema.release()
    kbi.reset_for_tests()


def test_kb_backlog_bounded():
    from services import kb_ingest as kbi

    for i in range(kbi._KB_BACKLOG_MAX + 10):
        kbi._enqueue_backlog("u", f"id-{i}", "a.txt")
    assert kbi.backlog_depth() == kbi._KB_BACKLOG_MAX
    kbi.reset_for_tests()


def test_kb_reaper_retries_from_disk(api_env, monkeypatch):
    import time as _time

    from services import kb_ingest as kbi
    from services.files import FileStore

    calls = []

    def _fake_ingest(uid, upid, name, data):
        calls.append((uid, upid, bytes(data)[:5]))

    monkeypatch.setattr("services.kb.ingest_document", _fake_ingest)
    store = FileStore("reaper-user")
    meta = store.save_upload(b"hello reaper world, this is text", "note.txt")

    kbi._enqueue_backlog("reaper-user", meta.id, str(meta.display_name))
    assert kbi.drain_backlog() == 1
    deadline = _time.time() + 10.0
    while _time.time() < deadline and not calls:
        _time.sleep(0.05)
    assert [c[:2] for c in calls] == [("reaper-user", meta.id)]
    assert calls[0][2] == b"hello"
    # Slot released again after the reaper worker finished.
    assert _wait_for_free_slots(kbi)


def test_kb_reaper_skips_deleted_upload(monkeypatch):
    from services import kb_ingest as kbi

    calls = []
    monkeypatch.setattr("services.kb.ingest_document", lambda *a: calls.append(a))
    assert _wait_for_free_slots(kbi)
    kbi._enqueue_backlog("ghost-user", "0123456789abcdef", "gone.txt")
    assert kbi.drain_backlog() == 1
    assert _wait_for_free_slots(kbi)  # worker fully done, slot freed
    assert calls == []  # deleted vault: silent no-op
    assert kbi.backlog_depth() == 0
    kbi.reset_for_tests()


def test_kb_reaper_stops_when_slots_busy():
    from services import kb_ingest as kbi

    assert _wait_for_free_slots(kbi)  # no stragglers from earlier tests
    kbi._enqueue_backlog("u", "id9", "a.txt")
    assert kbi._kb_ingest_sema.acquire(blocking=False)
    assert kbi._kb_ingest_sema.acquire(blocking=False)
    try:
        assert kbi.drain_backlog() == 0
        assert kbi.backlog_depth() == 1  # entry kept for the next pass
    finally:
        kbi._kb_ingest_sema.release()
        kbi._kb_ingest_sema.release()
    kbi.reset_for_tests()


def test_snapshot_skipped_when_temp_disk_tight(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("R2_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("R2_BUCKET", "pluto-data")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "s")
    from services import snapshots as snap

    snap._reset_for_tests()
    root = tmp_path / "data"
    (root / "users" / "alice").mkdir(parents=True)
    (root / "accounts.json").write_text('{"users": {}}', encoding="utf-8")

    def _no_client():
        raise AssertionError("no client expected on a skipped build")

    monkeypatch.setattr(snap, "_get_client", _no_client)
    monkeypatch.setattr(snap, "_temp_free_bytes", lambda: 0)
    snap.notify()
    assert snap._upload_now() is False
    snap._reset_for_tests()


def _wait_for_free_slots(kbi, n=2, timeout=10.0):
    """Poll until n slots are simultaneously acquirable (workers released)."""
    import time as _time

    deadline = _time.time() + timeout
    while _time.time() < deadline:
        held = 0
        while held < n and kbi._kb_ingest_sema.acquire(blocking=False):
            held += 1
        if held == n:
            for _ in range(n):
                kbi._kb_ingest_sema.release()
            return True
        for _ in range(held):
            kbi._kb_ingest_sema.release()
        _time.sleep(0.05)
    return False


def test_kb_ingest_runs_and_releases(monkeypatch):
    from backend.routers import uploads as up
    from services import kb_ingest as kbi

    calls = []

    def _fake_ingest(uid, upid, name, data):
        calls.append((uid, upid))

    monkeypatch.setattr("services.kb.ingest_document", _fake_ingest)
    assert _wait_for_free_slots(kbi)
    assert up.schedule_kb_ingest("u2", "id2", "b.txt", b"hello") is True
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if calls:
            break
        time.sleep(0.05)
    assert calls == [("u2", "id2")]
    # Slot released: both acquirable again (worker releases after ingest).
    assert _wait_for_free_slots(kbi)


# ---- Finding 3: file-backed snapshots ----

def test_snapshot_archive_to_file_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    from services import snapshots as snap

    root = tmp_path / "data"
    (root / "users" / "alice").mkdir(parents=True)
    (root / "accounts.json").write_text('{"users": {}}', encoding="utf-8")
    (root / "users" / "alice" / "chats.json").write_text('{"chats": []}', encoding="utf-8")

    archive = snap._build_archive_to_file(root)
    try:
        assert os.path.getsize(archive) > 0
        out = tmp_path / "restored"
        n = snap._safe_extract_file(archive, out)
        assert n >= 2
        assert (out / "accounts.json").exists()
    finally:
        if os.path.exists(archive):
            os.unlink(archive)


def test_snapshot_upload_streams_file_and_cleans_up(tmp_path, monkeypatch):
    import io as _io

    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("R2_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("R2_BUCKET", "pluto-data")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "s")
    from services import snapshots as snap

    snap._reset_for_tests()

    seen = {}

    class FakeS3:
        def put_object(self, Bucket, Key, Body):
            # Production path passes a file object, never full bytes.
            assert hasattr(Body, "read"), "snapshot upload must stream a file"
            seen["n"] = seen.get("n", 0) + 1
            seen["data"] = Body.read()
            return {}

        def get_object(self, Bucket, Key):
            return {"Body": _io.BytesIO(seen["data"])}

    monkeypatch.setattr(snap, "_get_client", lambda: FakeS3())
    root = tmp_path / "data"
    (root / "users" / "alice").mkdir(parents=True)
    (root / "accounts.json").write_text('{"users": {}}', encoding="utf-8")
    (root / "users" / "alice" / "chats.json").write_text('{"chats": []}', encoding="utf-8")

    assert snap._upload_now() is True
    assert seen.get("n") == 1
    # Temp archives cleaned up (only the data files remain).
    leftovers = [p for p in tmp_path.rglob("pluto-snap-*")]
    assert leftovers == []
    snap._reset_for_tests()


# ---- Finding 4: subprocess sandbox ----

def test_sandbox_happy_path():
    from services import codeexec

    res = codeexec.execute("print(2 + 3 * 4)")
    assert res.get("output", "").strip() == "14"


def test_sandbox_bigint_pow_times_out():
    from services import codeexec

    # Premise of Finding 4: this passes AST validation (not blocked).
    assert codeexec.validate_code("print(pow(10, 10**9))") is None
    started = time.time()
    res = codeexec.execute("print(pow(10, 10**9))")
    elapsed = time.time() - started
    assert "error" in res and "timed out" in res["error"]
    assert elapsed < 30


def test_sandbox_repeated_timeouts_do_not_accumulate():
    import threading as _th

    from services import codeexec

    before = _th.active_count()
    for _ in range(2):
        res = codeexec.execute("print(pow(10, 10**8))")
        assert "error" in res
    time.sleep(0.5)
    # No orphan worker threads accumulate per timed-out call.
    assert _th.active_count() <= before + 2


# ---- Finding 5: health single-flight ----

def test_health_probe_single_flight(monkeypatch):
    from backend.routers import meta as meta_mod

    calls = []

    def _fake_probe(timeout=20.0):
        calls.append(1)
        time.sleep(0.4)
        return "fake-tier"

    monkeypatch.setattr("agent.runtime.probe_live_tier", _fake_probe)
    monkeypatch.setenv("PLUTO_HEALTH_PROBE", "1")
    with meta_mod._live_cache_lock:
        meta_mod._live_cache.update({"at": 0.0, "tier": "stale-tier", "probing": False})

    results = []

    def _hit():
        try:
            results.append(meta_mod._cached_live_tier(["fake-tier"]))
        except Exception as e:  # pragma: no cover
            results.append(e)

    threads = [threading.Thread(target=_hit) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 8
    assert calls == [1], calls  # one provider probe, not eight
    assert all(r in ("stale-tier", "fake-tier") for r in results)
    with meta_mod._live_cache_lock:
        assert meta_mod._live_cache.get("probing") is False
        meta_mod._live_cache.update({"at": 0.0, "tier": None, "probing": False})


# ---- Finding 6: storage failures are 503 ----

class _FailingStore:
    def __init__(self, exc):
        self._exc = exc

    def list_uploads(self):
        raise self._exc

    def list_outputs(self):
        raise self._exc


class _Ctx:
    def __init__(self, store):
        self.user_id = "u"
        self.file_store = store


def test_list_uploads_storage_error_is_503():
    from backend.routers import uploads as up
    from services.files import FileValidationError
    from services.storage import StorageError

    with pytest.raises(HTTPException) as ei:
        up.list_uploads(_Ctx(_FailingStore(StorageError("disk gone"))))
    assert ei.value.status_code == 503
    # Validation-shaped emptiness still returns [].
    assert up.list_uploads(_Ctx(_FailingStore(FileValidationError("bad")))) == []


def test_list_artifacts_storage_error_is_503():
    from backend.routers import artifacts as art
    from services.files import FileValidationError
    from services.storage import StorageError

    with pytest.raises(HTTPException) as ei:
        art.list_artifacts(_Ctx(_FailingStore(StorageError("disk gone"))))
    assert ei.value.status_code == 503
    assert art.list_artifacts(_Ctx(_FailingStore(FileValidationError("bad")))) == []
