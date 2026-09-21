"""Task guidance: teaching gate + per-task specialist blocks (Agency mission).

The teaching override lives in SYSTEM_PROMPT (canonical) but is stripped
for non-teaching turns; specialist guidance rides matching task_type only.
Zero extra model/tool calls by construction — verify text shaping here.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import prompts as pm


def test_system_prompt_canonical_untouched():
    # Teaching tests assert on the full constant; gating must not move text.
    assert "## Concept:" in pm.SYSTEM_PROMPT
    assert "without re-fetching" in pm.SYSTEM_PROMPT


def test_non_teaching_turn_strips_teaching_block():
    out = pm._build_system_prompt("", "", "")
    assert "## Concept:" not in out
    assert pm._TEACHING_BLOCK_START not in out
    # Rest of the prompt survives: coding, grounding-adjacent, identity.
    assert "workspace_write" in out
    assert "Return only the user-facing answer." in out


def test_teaching_turn_keeps_full_text():
    out = pm._build_system_prompt("", "", "", teaching=True)
    assert "## Concept:" in out
    assert pm._TEACHING_BLOCK_START in out
    # Byte-identical to the historical full build (only memory/project
    # blocks and pre-flight follow; all empty here).
    assert out.startswith(pm.SYSTEM_PROMPT)


def test_strip_is_fail_closed():
    assert pm._strip_teaching_block("no markers here") == "no markers here"


def test_specialist_blocks_route_by_task_type():
    research = pm._build_system_prompt("", "", "", task_type="research")
    assert "Research discipline:" in research
    assert "Data/code discipline:" not in research

    data = pm._build_system_prompt("", "", "", task_type="data")
    assert "Data/code discipline:" in data

    creative = pm._build_system_prompt("", "", "", task_type="creative")
    assert "Generation discipline:" in creative

    multi = pm._build_system_prompt("", "", "", task_type="multi_step")
    assert "Multi-step discipline:" in multi
    # Done-criteria live in the multi_step block (where loops occur),
    # not as a global nudge (see latency mission: unproven, removed).
    assert "done-criteria" in multi


def test_unknown_and_simple_get_no_guidance():
    plain = pm._build_system_prompt("", "", "")
    assert "discipline:" not in plain
    simple = pm._build_system_prompt("", "", "", simple=True)
    assert "discipline:" not in simple
    assert "## Concept:" not in simple


def test_teaching_marker_matches_backend_suffix():
    from backend.teach import TEACHING_SUFFIX

    assert pm.TEACHING_INPUT_MARKER in TEACHING_SUFFIX
