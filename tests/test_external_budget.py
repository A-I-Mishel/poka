"""Batch 2 proofs: single-sourced budgets + per-result external gating.

- Context/token budget numbers live in services.limits exactly once;
  services.context_budget re-exports them (drift-proof by assertion).
- One tool batch can no longer land 24k external tokens against the
  12k budget: overflow tails are dropped per result with a fixed note.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_context_budgets_single_sourced():
    import services.context_budget as cb
    import services.limits as lim

    for name in ("CONTEXT_MAX_TOKENS", "CTX_HISTORY_TOKENS",
                 "CTX_MEMORY_TOKENS", "CTX_SUMMARY_TOKENS",
                 "CTX_EXTERNAL_TOKENS"):
        assert getattr(cb, name) == getattr(lim, name), name
    # Context-shaping splits stay owned by context_budget.
    assert cb.CTX_SYSTEM_TOKENS == 4000
    assert cb.CTX_CURRENT_TOKENS == 6000
    # The services facade still exposes every name.
    import services as svc

    for name in ("CONTEXT_MAX_TOKENS", "CTX_SYSTEM_TOKENS",
                 "CTX_CURRENT_TOKENS", "CTX_HISTORY_TOKENS",
                 "CTX_MEMORY_TOKENS", "CTX_SUMMARY_TOKENS",
                 "CTX_EXTERNAL_TOKENS"):
        assert getattr(svc, name) == getattr(cb, name), name


def _texts(monkeypatch, per_result_tokens, count):
    import agent.toolrun as tr

    monkeypatch.setattr(tr, "count_tokens", lambda t: len(t) // 4)
    return ["MARKER_R%d " % (i + 1) + "x" * (per_result_tokens * 4 - 10)
            for i in range(count)]


def test_overflow_tail_dropped_with_note(monkeypatch):
    from agent.toolrun import _fit_results_to_budget

    results = _texts(monkeypatch, 3000, 5)
    fitted, truncated = _fit_results_to_budget(results)
    assert truncated is True
    # 4 x 3000 fit; the 5th drops, replaced by the fixed note.
    assert len(fitted) == 5
    assert "MARKER_R4" in fitted[3]
    assert "MARKER_R5" not in "\n".join(fitted)
    assert fitted[-1].startswith("[budget] External content")


def test_under_budget_untouched(monkeypatch):
    from agent.toolrun import _fit_results_to_budget

    results = _texts(monkeypatch, 100, 3)
    fitted, truncated = _fit_results_to_budget(results)
    assert truncated is False
    assert fitted == results


def test_single_huge_result_kept_with_note(monkeypatch):
    from agent.toolrun import _fit_results_to_budget

    results = _texts(monkeypatch, 13000, 1)
    fitted, truncated = _fit_results_to_budget(results)
    # First result always kept (something beats nothing); note appended.
    assert truncated is True
    assert len(fitted) == 2
    assert fitted[0] == results[0]
    assert fitted[1].startswith("[budget] External content")


def test_empty_results_fit():
    from agent.toolrun import _fit_results_to_budget

    assert _fit_results_to_budget([]) == ([], False)
    assert _fit_results_to_budget(None) == ([], False)
