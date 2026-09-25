"""Executor saturation tests: bounded queue rejects fast with 503.

Under sustained load model/tool calls must fail fast (ExecutorBusyError
-> HTTP 503) instead of piling unbounded work into memory.
"""

import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from agent.executor import ExecutorBusyError, _BoundedExecutor
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def open_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLUTO_USER_ID", raising=False)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    # Saturation tests post throwaway "hi": keep them on the model path.
    monkeypatch.setenv("PLUTO_GREETINGS", "0")
    return tmp_path


def _saturate(workers=1):
    """Return (executor, release) with worker(s) blocked and queue full."""
    gate = threading.Event()
    ex = _BoundedExecutor(workers, "test")
    first = ex.submit(gate.wait)
    deadline = time.time() + 5.0
    while not first.running():
        assert time.time() < deadline, "worker never picked up the task"
        time.sleep(0.01)
    capacity = max(1, workers * 2)
    fillers = [ex.submit(lambda: None) for _ in range(capacity)]
    return ex, gate, [first] + fillers


def test_submit_rejects_when_full():
    ex, gate, pendings = _saturate(1)
    try:
        with pytest.raises(ExecutorBusyError):
            ex.submit(lambda: None)
    finally:
        gate.set()
        for f in pendings:
            f.result(timeout=5)


def test_submit_accepts_when_room():
    ex = _BoundedExecutor(2, "test-room")
    try:
        assert ex.submit(lambda: 42).result(timeout=5) == 42
    finally:
        pass


def test_call_bounded_propagates_busy_fast(monkeypatch):
    import agent.executor as executor

    ex, gate, pendings = _saturate(1)
    monkeypatch.setattr(executor, "_bounded_pool", ex)
    try:
        started = time.time()
        with pytest.raises(ExecutorBusyError):
            executor._call_bounded(lambda: 1, timeout=30.0, what="test call")
        assert time.time() - started < 5.0
    finally:
        monkeypatch.undo()
        gate.set()
        for f in pendings:
            f.result(timeout=5)


def test_send_maps_saturation_to_503(open_env, monkeypatch):
    def _answer(user_input, history=None, **kwargs):
        raise ExecutorBusyError("Executor 'pluto-bounded' is saturated.")

    monkeypatch.setattr(agent, "answer_with_fallback", _answer)
    from backend.main import app

    with TestClient(app) as client:
        res = client.post("/api/chat/send", json={"content": "hi"})
        assert res.status_code == 503, res.text
        assert "busy" in res.json()["detail"].lower()
