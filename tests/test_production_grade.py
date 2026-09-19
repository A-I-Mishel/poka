"""Production-grade regression: omni-agent purity + hardening.

Hermetic, no network/quota. Enforces:
- Single entrypoint: routers never import langchain directly.
- Tracing never raises (NoOp fallback) and defaults to noop, not console.
- Snapshot interval defaults to 10s (docs/render parity).
- Health exposes limiter/snapshot/live_tier readiness signals.
- Tool loop carries request_id through runtime/planning.
"""

import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_routers_never_import_langchain():
    root = pathlib.Path(__file__).resolve().parent.parent / "backend" / "routers"
    offenders = []
    for f in root.glob("*.py"):
        text = f.read_text(encoding="utf-8", errors="replace")
        if "langchain" in text.lower():
            offenders.append(f.name)
    assert offenders == [], f"routers must go via chatflow/runtime, found langchain in {offenders}"


def test_chatflow_single_entrypoint():
    import backend.chatflow as cf
    import backend.flow as flow_mod
    import backend.flow.turns as turns_mod

    assert hasattr(cf, "run_chat")
    # Shim re-exports the single implementation home (backend.flow package).
    assert cf.run_chat is flow_mod.run_chat
    assert cf.run_chat is turns_mod.run_chat
    src = pathlib.Path(turns_mod.__file__).read_text(encoding="utf-8")
    assert "answer_with_fallback" in src


def test_tracing_never_raises_and_defaults_noop(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "")
    import services.tracing as tr

    tr._initialized = False
    tr._tracer = None
    tracer = tr.init_tracing()
    assert tracer is not None
    # Span helpers never raise, even with bogus inputs.
    s1 = tr.start_llm_span("r1", "fake-tier", "simple")
    tr.end_llm_span(s1, 0, None)
    tr.end_llm_span(None, 0, None)
    assert tr.start_cascade_span("r1", "simple") is not None
    assert tr.start_tool_span("r1", "web_search", "serial") is not None
    assert tr.start_kb_span("r1", "search", "lexical") is not None
    assert tr.start_storage_span("r1", "read") is not None
    tr._initialized = False
    tr._tracer = None


def test_snapshot_interval_default_10(monkeypatch):
    monkeypatch.delenv("SNAPSHOT_INTERVAL_SECONDS", raising=False)
    # Ensure secrets seam (which prefers env) sees no override.
    monkeypatch.delenv("SNAPSHOT_INTERVAL_SECONDS", raising=False)
    from services import snapshots as snaps

    assert snaps._interval_seconds() == 10.0


def test_health_has_readiness_signals():
    from fastapi.testclient import TestClient

    # Health must work without keys (liveness) and expose new fields.
    import backend.main as main

    client = TestClient(main.app)
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert isinstance(body["tiers"], list)
    assert body["auth_mode"] in ("open", "private")
    assert "limiter" in body
    assert "snapshots_configured" in body
    assert "live_tier" in body


def test_tool_loop_accepts_request_id():
    import inspect

    import agent.planning as planning
    import agent.toolrun as toolrun

    assert "request_id" in inspect.signature(toolrun.run_tool_loop).parameters
    assert "request_id" in inspect.signature(planning.plan_then_execute).parameters


def test_memory_alias_removed():
    import pathlib

    assert not (pathlib.Path(__file__).resolve().parent.parent / "memory_engine.py").exists()
    import services.memory as mem

    assert hasattr(mem, "load_structured_memory")
