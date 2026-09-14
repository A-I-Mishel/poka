"""Snapshot tests: R2 backup/restore shim for free-tier durability.

The shim must be a strict no-op when R2_* is unset (local dev behavior
unchanged), round-trip data/ through a fake object store, never clobber
local data, and never let backup failures break the write path.
"""

import io
import os
import sys
import tarfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import snapshots as snap

_R2_VARS = (
    "R2_ACCOUNT_ID",
    "R2_BUCKET",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "SNAPSHOT_ENDPOINT_URL",
    "SNAPSHOT_REGION",
    "SNAPSHOT_INTERVAL_SECONDS",
    "SNAPSHOT_KEY",
    "SNAPSHOT_TIMEOUT_SECONDS",
    "SNAPSHOT_ENABLED",
)


class _MissingError(Exception):
    """Stands in for botocore NoSuchKey on a fresh bucket."""

    def __init__(self):
        super().__init__("NoSuchKey")
        self.response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3:
    """In-memory S3-compatible store (no network, no boto3)."""

    def __init__(self):
        self.objects = {}
        self.puts = 0

    def put_object(self, Bucket, Key, Body):
        data = Body.read() if hasattr(Body, "read") else bytes(Body)
        self.objects[(Bucket, Key)] = data
        self.puts += 1
        return {}

    def get_object(self, Bucket, Key):
        try:
            data = self.objects[(Bucket, Key)]
        except KeyError:
            raise _MissingError()
        return {"Body": io.BytesIO(data)}


@pytest.fixture(autouse=True)
def _ctx(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    for var in _R2_VARS:
        monkeypatch.delenv(var, raising=False)
    snap._reset_for_tests()
    yield
    snap._reset_for_tests()


def _configure(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("R2_BUCKET", "pluto-data")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret")


def _seed_data(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "accounts.json").write_text('{"users": {}}', encoding="utf-8")
    chats = root / "users" / "alice" / "chats.json"
    chats.parent.mkdir(parents=True, exist_ok=True)
    chats.write_text('{"chats": []}', encoding="utf-8")


def test_inert_when_unconfigured(tmp_path):
    assert snap.configured() is False
    snap.notify()  # must not start threads or raise
    assert snap.flush() is False
    assert snap.maybe_restore() is False
    st = snap.status()
    assert st["configured"] is False
    assert st["worker_alive"] is False


def test_placeholder_values_do_not_count(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("R2_ACCOUNT_ID", "your_account_id")
    assert snap.configured() is False


def test_disabled_flag_overrides_vars(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("SNAPSHOT_ENABLED", "false")
    assert snap.configured() is False
    snap.notify()
    assert snap.status()["worker_alive"] is False


def test_r2_endpoint_built_from_account_id(monkeypatch):
    _configure(monkeypatch)
    cfg = snap._backend_config()
    assert cfg is not None
    assert cfg["endpoint"] == "https://test-account.r2.cloudflarestorage.com"
    assert cfg["region"] == "auto"
    assert cfg["path_style"] is False


def test_supabase_style_config_needs_no_account_id(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "pluto-data")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "supa-key-id")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "supa-secret")
    monkeypatch.setenv(
        "SNAPSHOT_ENDPOINT_URL",
        "https://xyzcompany.storage.supabase.co/storage/v1/s3",
    )
    monkeypatch.setenv("SNAPSHOT_REGION", "ap-south-1")
    assert snap.configured() is True
    cfg = snap._backend_config()
    assert cfg is not None
    assert cfg["endpoint"] == "https://xyzcompany.storage.supabase.co/storage/v1/s3"
    assert cfg["region"] == "ap-south-1"
    assert cfg["path_style"] is True


def test_roundtrip_through_supabase_style_config(tmp_path, monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "pluto-data")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "supa-key-id")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "supa-secret")
    monkeypatch.setenv("SNAPSHOT_ENDPOINT_URL", "https://xyzcompany.storage.supabase.co/storage/v1/s3")
    monkeypatch.setenv("SNAPSHOT_REGION", "ap-south-1")
    fake = FakeS3()
    monkeypatch.setattr(snap, "_get_client", lambda: fake)
    root = tmp_path / "data"
    _seed_data(root)

    assert snap._upload_now() is True
    assert fake.puts == 1

    import shutil

    shutil.rmtree(root)
    assert snap.maybe_restore() is True
    assert (root / "accounts.json").read_text(encoding="utf-8") == '{"users": {}}'


def test_roundtrip_through_fake_store(tmp_path, monkeypatch):
    _configure(monkeypatch)
    fake = FakeS3()
    monkeypatch.setattr(snap, "_get_client", lambda: fake)
    root = tmp_path / "data"
    _seed_data(root)

    assert snap._upload_now() is True
    assert fake.puts == 1

    # Simulate a Render restart: wipe the local disk, then boot.
    for child in (root / "users", root / "accounts.json"):
        if child.is_dir():
            import shutil

            shutil.rmtree(child)
        elif child.exists():
            child.unlink()
    assert snap._local_data_present() is False

    assert snap.maybe_restore() is True
    assert (root / "accounts.json").read_text(encoding="utf-8") == '{"users": {}}'
    assert (root / "users" / "alice" / "chats.json").exists()


def test_upload_skipped_when_unchanged(tmp_path, monkeypatch):
    _configure(monkeypatch)
    fake = FakeS3()
    monkeypatch.setattr(snap, "_get_client", lambda: fake)
    _seed_data(tmp_path / "data")

    assert snap._upload_now() is True
    assert snap._upload_now() is True  # second call: fingerprint match, no PUT
    assert fake.puts == 1


def test_restore_never_clobbers_local_data(tmp_path, monkeypatch):
    _configure(monkeypatch)
    fake = FakeS3()
    monkeypatch.setattr(snap, "_get_client", lambda: fake)
    root = tmp_path / "data"
    _seed_data(root)
    assert snap._upload_now() is True

    (root / "accounts.json").write_text('{"users": {"local": 1}}', encoding="utf-8")
    assert snap.maybe_restore() is False
    assert (root / "accounts.json").read_text(encoding="utf-8") == '{"users": {"local": 1}}'


def test_restore_repairs_partial_wipe(tmp_path, monkeypatch):
    _configure(monkeypatch)
    fake = FakeS3()
    monkeypatch.setattr(snap, "_get_client", lambda: fake)
    root = tmp_path / "data"
    _seed_data(root)
    assert snap._upload_now() is True

    # Half-wipe: the auth registry survived, user data vanished.
    import shutil

    shutil.rmtree(root / "users")
    assert snap._local_data_partial() is True
    assert snap._local_data_present() is True

    assert snap.maybe_restore() is True
    assert (root / "users" / "alice" / "chats.json").exists()


def test_partial_wipe_skips_upload(tmp_path, monkeypatch):
    """Half-wiped local must never be pushed over a good remote snapshot."""
    _configure(monkeypatch)
    fake = FakeS3()
    monkeypatch.setattr(snap, "_get_client", lambda: fake)
    root = tmp_path / "data"
    _seed_data(root)
    assert snap._upload_now() is True

    # Half-wipe: push must be suppressed (good remote preserved).
    import shutil

    shutil.rmtree(root / "users")
    assert snap._local_data_partial() is True
    (root / "data.log").write_text("new", encoding="utf-8")
    snap.notify()
    assert snap._upload_now() is False
    assert fake.puts == 1


def test_open_mode_layout_is_not_partial(tmp_path):
    """users/ without accounts.json is the normal open-mode layout."""
    root = tmp_path / "data"
    chats = root / "users" / "guest" / "chats.json"
    chats.parent.mkdir(parents=True)
    chats.write_text('{"chats": []}', encoding="utf-8")
    assert snap._local_data_partial() is False
    assert snap._local_data_present() is True


def test_restore_with_no_remote_snapshot_is_quiet(tmp_path, monkeypatch):
    _configure(monkeypatch)
    fake = FakeS3()  # empty bucket
    monkeypatch.setattr(snap, "_get_client", lambda: fake)
    assert snap.maybe_restore() is False


def test_archive_rejects_path_escape(tmp_path, monkeypatch):
    _configure(monkeypatch)
    fake = FakeS3()
    monkeypatch.setattr(snap, "_get_client", lambda: fake)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="../../evil.txt")
        payload = b"pwned"
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
        info2 = tarfile.TarInfo(name="accounts.json")
        good = b"{}"
        info2.size = len(good)
        tar.addfile(info2, io.BytesIO(good))
    fake.objects[("pluto-data", "pluto-data-latest.tar.gz")] = buf.getvalue()

    assert snap.maybe_restore() is True
    assert not (tmp_path / "evil.txt").exists()
    assert (tmp_path / "data" / "accounts.json").exists()


def test_write_json_hook_fires_notify(tmp_path, monkeypatch):
    from services import storage

    calls = []
    monkeypatch.setattr(snap, "notify", lambda: calls.append(1))
    # Rebind: storage hook does `from services.snapshots import notify`
    target = tmp_path / "data" / "users" / "bob" / "chats.json"
    storage._write_json(target, {"chats": []})
    assert target.exists()
    assert len(calls) == 1


def test_atomic_bytes_hook_fires_notify(tmp_path, monkeypatch):
    from services import files

    calls = []
    monkeypatch.setattr(snap, "notify", lambda: calls.append(1))
    dest = tmp_path / "data" / "users" / "bob" / "blob.bin"
    dest.parent.mkdir(parents=True, exist_ok=True)
    files._atomic_write_bytes(dest, b"hello")
    assert dest.read_bytes() == b"hello"
    assert len(calls) == 1


def test_notify_failure_can_never_break_writes(tmp_path, monkeypatch):
    from services import storage

    def _boom():
        raise RuntimeError("r2 is down")

    # Hook-level guard absorbs the failure; the write must succeed.
    monkeypatch.setattr("services.snapshots.notify", _boom)
    target = tmp_path / "data" / "x.json"
    storage._write_json(target, {"ok": True})
    assert target.exists()


def test_cli_status_without_config(capsys):
    assert snap.main(["--status"]) == 0
    out = capsys.readouterr().out
    assert "configured=False" in out


def test_cli_upload_and_download(tmp_path, monkeypatch, capsys):
    _configure(monkeypatch)
    fake = FakeS3()
    monkeypatch.setattr(snap, "_get_client", lambda: fake)
    root = tmp_path / "data"
    _seed_data(root)

    assert snap.main(["--upload"]) == 0
    assert fake.puts == 1

    import shutil

    shutil.rmtree(root)
    assert snap.main(["--download"]) == 0
    assert (root / "accounts.json").exists()
    capsys.readouterr()
