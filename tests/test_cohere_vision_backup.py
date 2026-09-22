"""Cohere as backup vision lane behind Gemini (no network).

Cohere only sees image content when its configured model is
vision-capable (COHERE_MODEL=command-a-vision-*); the gates below merely
admit the tier name into vision paths in backup position. Unknown tiers
stay text-only.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.vision import vision_supported_tier


def test_cohere_admitted_unknown_stays_text_only():
    assert vision_supported_tier("Cohere") is True
    assert vision_supported_tier("OpenRouter Ling VL") is True
    assert vision_supported_tier("Gemini 3.8 Flash") is True
    assert vision_supported_tier("Gemini 3.7 Flash") is True
    assert vision_supported_tier("Gemini 3.6 Flash") is True
    assert vision_supported_tier("Gemini 3.5 Flash") is True
    assert vision_supported_tier("Groq") is False
    assert vision_supported_tier("Defunct Lane") is False
    assert vision_supported_tier("OpenRouter Qwen 27B") is False
    assert vision_supported_tier("") is False
    assert vision_supported_tier(None) is False


def test_bridge_converter_backup_order():
    # Single source: the bridge alias IS the canonical vision order.
    from services.image_bridge import _CONVERTER_TIERS
    from services.vision import VISION_TIER_ORDER

    assert _CONVERTER_TIERS is VISION_TIER_ORDER
    assert list(_CONVERTER_TIERS) == [
        "Gemini 3.8 Flash", "Gemini 3.7 Flash",
        "Gemini 3.6 Flash", "Gemini 3.5 Flash", "Cohere",
        "OpenRouter Ling VL"]


def test_runtime_vision_tier_names_mirror():
    # Single source: the runtime alias IS the canonical vision order.
    from agent import runtime as rt
    from services.vision import VISION_TIER_ORDER

    assert rt._VISION_TIER_NAMES is VISION_TIER_ORDER
    assert "Cohere" in rt._VISION_TIER_NAMES
    assert "OpenRouter Ling VL" in rt._VISION_TIER_NAMES
    assert rt._VISION_TIER_NAMES.index("Gemini 3.5 Flash") < \
        rt._VISION_TIER_NAMES.index("Cohere")
    assert rt._VISION_TIER_NAMES.index("Cohere") < \
        rt._VISION_TIER_NAMES.index("OpenRouter Ling VL")


def test_degraded_message_is_provider_neutral(monkeypatch):
    import agent.runtime as rt

    monkeypatch.setattr(rt, "_vision_unavailable_reason",
                        lambda: "cooling down (~5m)")
    res = rt._vision_degraded("req-1")
    assert res["active_tier"] == "vision-unavailable"
    assert "no vision-capable model answered" in res["output"]
    assert "Switching to Gemini" not in res["output"]
    assert "<5MB" in res["output"]


def test_reason_all_unconfigured_neutral(monkeypatch):
    import agent.runtime as rt

    monkeypatch.setattr(
        "agent.cascade.tier_status_snapshot",
        lambda *a, **k: [
            {"name": "Gemini 3.8 Flash", "configured": False,
             "skipped": False, "cooldown_remaining_s": 0.0,
             "last_error_kind": ""},
            {"name": "Gemini 3.7 Flash", "configured": False,
             "skipped": False, "cooldown_remaining_s": 0.0,
             "last_error_kind": ""},
            {"name": "Gemini 3.6 Flash", "configured": False,
             "skipped": False, "cooldown_remaining_s": 0.0,
             "last_error_kind": ""},
            {"name": "Gemini 3.5 Flash", "configured": False,
             "skipped": False, "cooldown_remaining_s": 0.0,
             "last_error_kind": ""},
            {"name": "Cohere", "configured": False,
             "skipped": False, "cooldown_remaining_s": 0.0,
             "last_error_kind": ""},
        ],
    )
    reason = rt._vision_unavailable_reason()
    assert "not configured" in reason
    assert "GEMINI_API_KEY" not in reason
