"""State-aware vision-degraded reason (Phase C, Gemini-only).

_vision_unavailable_reason() must distinguish "not configured" from
"cooling down with a remaining wait" so users wait instead of
rapid-retrying (retries re-arm the cooldown they wait out).
_format_cooldown() renders compact wait times. Never raises.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import runtime as _rt


def _snap(rows):
    return [
        {
            "name": name,
            "configured": configured,
            "skipped": skipped,
            "cooldown_remaining_s": remaining,
            "last_error_kind": kind,
        }
        for name, configured, skipped, remaining, kind in rows
    ]


def test_format_cooldown_units():
    assert _rt._format_cooldown(6 * 3600) == "~6h"
    assert _rt._format_cooldown(6 * 3600 + 30 * 60) == "~6h30m"
    assert _rt._format_cooldown(600) == "~10m"
    assert _rt._format_cooldown(45) == "~45s"
    assert _rt._format_cooldown(0) == "~0s"
    assert _rt._format_cooldown("junk") == ""


def test_not_configured(monkeypatch):
    import agent.runtime as rt

    monkeypatch.setattr(
        "agent.cascade.tier_status_snapshot",
        lambda *a, **k: _snap([
            ("Gemini 3.6 Flash", False, False, 0.0, ""),
            ("Gemini 3.5 Flash", False, False, 0.0, ""),
        ]),
    )
    assert "not configured" in rt._vision_unavailable_reason()


def test_cooling_reports_wait(monkeypatch):
    import agent.runtime as rt

    monkeypatch.setattr(
        "agent.cascade.tier_status_snapshot",
        lambda *a, **k: _snap([
            ("Gemini 3.6 Flash", True, True, 5.5 * 3600, "rate_limit"),
            ("Gemini 3.5 Flash", True, True, 600.0, "rate_limit"),
        ]),
    )
    reason = rt._vision_unavailable_reason()
    assert "rate-limited" in reason
    assert "~5h30m" in reason
    assert "cooling down" in reason


def test_transient_cooling_no_double_cool_word(monkeypatch):
    import agent.runtime as rt

    monkeypatch.setattr(
        "agent.cascade.tier_status_snapshot",
        lambda *a, **k: _snap([
            ("Gemini 3.6 Flash", True, True, 90.0, "unknown"),
            ("Gemini 3.5 Flash", True, False, 0.0, ""),
        ]),
    )
    reason = rt._vision_unavailable_reason()
    assert "~1m" in reason or "~2m" in reason


def test_snapshot_failure_falls_back(monkeypatch):
    import agent.runtime as rt

    def _boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr("agent.cascade.tier_status_snapshot", _boom)
    monkeypatch.setattr("agent.cascade.last_tier_error", lambda name: None)
    assert rt._vision_unavailable_reason() == "unavailable"
