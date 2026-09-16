"""Observability stack: middleware correlation IDs, metrics, detailed health.

Hermetic like the rest of the suite: tmp PLUTO_DATA_DIR, no network.
Covers the previously unwired middleware + router: request-ID echo,
Prometheus exposition, authenticated detailed health, and the helper
functions backing the dependency checks.
"""

import os
import re
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backend.main as main


@pytest.fixture()
def api_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "obs-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    from backend.deps import clear_all_store_caches

    clear_all_store_caches()
    yield
    clear_all_store_caches()


@pytest.fixture()
def client(api_env):
    with TestClient(main.app) as handle:
        yield handle


def test_request_id_echoed_when_provided(client):
    res = client.get("/api/health", headers={"X-Request-Id": "probe-123"})
    assert res.status_code == 200
    assert res.headers.get("X-Request-Id") == "probe-123"


def test_request_id_generated_when_absent(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    generated = res.headers.get("X-Request-Id", "")
    assert re.fullmatch(r"[0-9a-f]{12}", generated), generated


def test_metrics_endpoint_exposes_pluto_metrics(client):
    client.get("/api/health")
    res = client.get("/api/metrics")
    assert res.status_code == 200
    assert "pluto_" in res.text
    assert "http" in res.text


def test_detailed_health_open_mode(client):
    res = client.get("/api/health/detailed")
    assert res.status_code == 200
    body = res.json()
    assert set(("storage", "redis", "faiss", "llm_tiers")) <= set(body["checks"])
    assert body["checks"]["storage"]["ok"] is True
    assert body["checks"]["redis"]["ok"] is True
    assert "uptime_seconds" in body
    assert body["ok"] is True


def test_detailed_health_private_requires_auth(client, monkeypatch):
    monkeypatch.setenv("PLUTO_AUTH_MODE", "private")
    # No credential at all: drop the fixture's env identity too.
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    assert client.get("/api/health/detailed").status_code == 401
    # Liveness and metrics stay public for orchestrators/scrapers.
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/metrics").status_code == 200


def test_debug_heap_open_mode(client):
    # Doc stub (like the CPU profile endpoint): guidance, no live snapshot.
    res = client.get("/api/debug/pprof/heap")
    assert res.status_code == 200
    assert "message" in res.json()


def test_redis_client_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    from services.ratelimit_redis import get_redis_client

    assert get_redis_client() is None


def test_detailed_health_reports_faiss_census(client):
    res = client.get("/api/health/detailed")
    assert res.status_code == 200
    faiss = res.json()["checks"]["faiss"]
    assert faiss["ok"] is True
    assert faiss["indexed_users"] == 0
