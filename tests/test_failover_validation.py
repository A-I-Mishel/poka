"""Final validation: original real-world failover scenario.

Model A has already read a PDF, read a document, analyzed an image
(bridge transcript), executed tools, and produced intermediates — then
fails early / in the middle / after substantial work / near completion.
Model B must continue from Pluto's preserved state without re-upload
asks, re-provided text, repeated tool calls, or restarted work.

All tools execute FOR REAL (vault PDF/document, stdlib logic); only
model weights are scripted and the vision converter is stubbed (free
quota is exhausted live). Structural assertions prove B received
everything: with all resource contents in its messages, no re-upload
or redo can be necessary.
"""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.budget import RequestBudget
from agent.toolrun import run_tool_loop

PDF_MARKER = "PDF_MARKER_ALPHA_quartz_revenue_44000"
DOC_MARKER = "DOC_MARKER_BETA_launch_checklist_item7"
IMAGE_MARKER = "IMAGE_MARKER_GAMMA_circuit_diagram_R3"


class ScriptLLM:
    def __init__(self, script):
        self._script = list(script)
        self.seen_messages = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        from types import SimpleNamespace

        self.seen_messages = list(messages or [])
        item = self._script.pop(0) if self._script else "ok"
        if isinstance(item, Exception):
            raise item
        text, calls = item if isinstance(item, tuple) else (item, [])
        return SimpleNamespace(content=text, tool_calls=calls)


import pytest


@pytest.fixture(autouse=True)
def _unbind_user():
    yield
    try:
        from services.context import set_current_user_id, set_limit_key

        set_current_user_id(None)
        set_limit_key(None)
    except Exception:
        pass


def _ctx_with_vault(tmp_path, monkeypatch, uid="valid-user"):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", uid)
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from services.context import set_current_user_id
    from services.files import FileStore

    # Stay bound: real tools resolve the vault through request context,
    # exactly like production's thread re-binding (unbound by fixture).
    set_current_user_id(uid)
    store = FileStore(uid)

    from tools.make_tool import _build_pdf, _parse_blocks

    pdf_bytes = _build_pdf("Report", _parse_blocks(
        "# Quarterly report\n\n" + PDF_MARKER + " total shown.\n"))
    pdf = store.save_upload(pdf_bytes, "report.pdf")

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, format="PNG")
    img = store.save_upload(buf.getvalue(), "photo.png")

    doc = store.save_upload(
        ("Deployment notes\n" + DOC_MARKER + " done.\n").encode("utf-8"),
        "notes.txt")
    return pdf.id, doc.id, img.id


def _counting_executor(monkeypatch):
    import agent.toolrun as toolrun_mod

    counts = {}
    real = toolrun_mod._execute_tool_calls_parallel

    def _counting(tool_calls, budget):
        for tc in tool_calls or []:
            name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
            counts[str(name)] = counts.get(str(name), 0) + 1
        return real(tool_calls, budget)

    monkeypatch.setattr(toolrun_mod, "_execute_tool_calls_parallel", _counting)
    return counts


def _provider(sequence):
    order = list(sequence)

    def _next():
        if not order:
            raise RuntimeError("no live tier")
        return order.pop(0)

    return _next


def _call(name, **args):
    return {"name": name, "args": dict(args), "id": "1"}


def _texts(messages):
    out = []
    for m in messages or []:
        content = getattr(m, "content", "")
        out.append(content if isinstance(content, str) else str(content))
    return "\n".join(out)


def test_fail_early_clean_start(tmp_path, monkeypatch):
    """A dies before any tool runs: B runs everything exactly once."""
    pdf_id, _, _ = _ctx_with_vault(tmp_path, monkeypatch)
    counts = _counting_executor(monkeypatch)

    dead = ScriptLLM([RuntimeError("A down")])
    b = ScriptLLM([
        ("reading now", [_call("read_pdf", upload_id=pdf_id)]),
        ("final from B", []),
    ])
    # Provider serves A (dead instantly) then B; B runs the tools itself.
    out = run_tool_loop(
        dead, "summarize the report", [], max_rounds=4,
        budget=RequestBudget(),
        llm_provider=_provider([("A", dead), ("B", b), ("B", b)]))
    assert out == "final from B"
    assert counts.get("read_pdf") == 1
    assert PDF_MARKER in _texts(b.seen_messages)


def test_fail_middle_keeps_pdf_results(tmp_path, monkeypatch):
    """A reads the PDF, dies on round 2: B continues, no re-execution."""
    pdf_id, _, _ = _ctx_with_vault(tmp_path, monkeypatch)
    counts = _counting_executor(monkeypatch)

    a = ScriptLLM([
        ("reading now", [_call("read_pdf", upload_id=pdf_id)]),
        RuntimeError("A died mid-task"),
    ])
    b = ScriptLLM([("final from B", [])])
    # Round 1 -> A (reads PDF); round 2 -> A raises -> same-round retry
    # serves B with A's results already in the messages.
    out = run_tool_loop(
        a, "summarize the report", [], max_rounds=4,
        budget=RequestBudget(),
        llm_provider=_provider([("A", a), ("A", a), ("B", b)]))
    assert out == "final from B"
    assert counts.get("read_pdf") == 1, counts
    blob = _texts(b.seen_messages)
    assert PDF_MARKER in blob, "B never received A's PDF results"


def test_fail_after_substantial_work_no_redo(tmp_path, monkeypatch):
    """A reads PDF + document, dies on round 3: both results reach B once."""
    pdf_id, doc_id, _ = _ctx_with_vault(tmp_path, monkeypatch)
    counts = _counting_executor(monkeypatch)

    a = ScriptLLM([
        ("reading pdf", [_call("read_pdf", upload_id=pdf_id)]),
        ("reading doc", [_call("read_document", upload_id=doc_id)]),
        RuntimeError("A died late"),
    ])
    b = ScriptLLM([("final from B", [])])
    # Rounds 1-2 -> A (both tools); round 3 -> A raises -> B continues.
    out = run_tool_loop(
        a, "summarize the report and notes", [], max_rounds=4,
        budget=RequestBudget(),
        llm_provider=_provider([("A", a), ("A", a), ("A", a), ("B", b)]))
    assert out == "final from B"
    assert counts.get("read_pdf") == 1, counts
    assert counts.get("read_document") == 1, counts
    blob = _texts(b.seen_messages)
    assert PDF_MARKER in blob
    assert DOC_MARKER in blob


def test_fail_near_completion_synthesis_failover(tmp_path, monkeypatch):
    """A finishes all tool rounds, dies at final synthesis: B synthesizes."""
    pdf_id, _, _ = _ctx_with_vault(tmp_path, monkeypatch)
    counts = _counting_executor(monkeypatch)

    a = ScriptLLM([
        ("reading now", [_call("read_pdf", upload_id=pdf_id)]),
        ("more reading", [_call("check_logic", operation="valid",
                                premises="p -> q\np", conclusion="q")]),
        RuntimeError("A died at synthesis"),
    ])
    b = ScriptLLM([("synthesized by B", [])])
    out = run_tool_loop(
        a, "summarize the report and validate", [], max_rounds=2,
        budget=RequestBudget(),
        llm_provider=_provider([("A", a), ("A", a), ("B", b)]))
    assert out == "synthesized by B"
    assert counts.get("read_pdf") == 1, counts
    assert counts.get("check_logic") == 1, counts


def test_full_turn_image_pdf_failover_no_reupload(tmp_path, monkeypatch):
    """Public entry point: image analyzed + PDF read, A dies, B continues.

    B's incoming messages must contain the image transcript AND the PDF
    text: with every resource present, asking to re-upload or re-provide
    text cannot be necessary.
    """
    pdf_id, _, img_id = _ctx_with_vault(tmp_path, monkeypatch)
    counts = _counting_executor(monkeypatch)

    from agent import runtime as rt_mod
    from services.context import set_current_user_id

    set_current_user_id("valid-user")
    note = ("<untrusted-tool-output>\n[image photo.png — readout]\n"
            f"Transcript:\n{IMAGE_MARKER} visible\n</untrusted-tool-output>")
    monkeypatch.setattr("services.image_bridge.describe_image_for_text",
                        lambda uid, question_hint="", budget=None: note)

    a = ScriptLLM([
        ("reading pdf", [_call("read_pdf", upload_id=pdf_id)]),
        RuntimeError("A died mid-task"),
    ])
    b = ScriptLLM([("solved by B", [])])
    try:
        res = rt_mod.answer_with_fallback(
            "solve the questions in the report and photo",
            image_upload_ids=[img_id],
            tiers=[("A", lambda: a), ("B", lambda: b)])
    finally:
        set_current_user_id(None)
    assert res["active_tier"] == "B"
    assert res["output"] == "solved by B"
    assert counts.get("read_pdf") == 1, counts
    blob = _texts(b.seen_messages)
    assert PDF_MARKER in blob, "B missing A's PDF results"
    assert IMAGE_MARKER in blob, "B missing the image transcript"
    assert "read_pdf" in res["tools_used"]
