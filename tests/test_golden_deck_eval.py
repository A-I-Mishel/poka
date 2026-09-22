"""Golden-deck eval: answer-key grading for lesson correctness (no network).

The cascade validator checks citation FORMAT; this checks FACTS against a
human-verified key (tests/tsp_golden_key.json). Deterministic keyword
grading — free forever, no model judge, no quota spent.

v1 scope: required-keyword presence only, no forbidden lists. Reason: good
exam-trap sentences legitimately mention the confusable term (e.g. the
Hamilton/Euler trap names Euler wording), so forbidden-substring checks
would fail correct answers. Revisit only with word-sense-aware grading.

Future use: judge new lanes (local 3B, Qwen/GLM trial verdicts) via
evaluate_text() against the same key — same bar for every model.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

KEY_PATH = os.path.join(os.path.dirname(__file__), "tsp_golden_key.json")


def load_key(path=KEY_PATH):
    """Load and validate the answer key (fail-loud on bad shape)."""
    with open(path, encoding="utf-8") as f:
        key = json.load(f)
    assert isinstance(key, dict) and key.get("deck"), "key needs a deck name"
    entries = key.get("entries")
    assert isinstance(entries, list) and entries, "key needs entries"
    seen = set()
    for entry in entries:
        assert isinstance(entry, dict), "entry must be an object"
        assert entry.get("id") and entry.get("question"), "entry needs id + question"
        assert entry["id"] not in seen, f"duplicate id: {entry['id']}"
        seen.add(entry["id"])
        required = entry.get("required")
        assert isinstance(required, list) and required, \
            f"entry {entry['id']} needs non-empty required keywords"
    return key


def grade_entry(entry, answer):
    """Score one entry: fraction of required keywords present (never raises)."""
    try:
        text = str(answer or "").lower()
        required = [str(k).lower() for k in (entry.get("required") or [])]
        matched = [k for k in required if k and k in text]
        missing = [k for k in required if k and k not in text]
        total = max(1, len(required))
        return {"score": len(matched) / total,
                "matched": matched, "missing": missing}
    except Exception:
        return {"score": 0.0, "matched": [], "missing": list(entry.get("required") or [])}


def evaluate_text(key, answer):
    """Score full text across all entries; overall is the mean (never raises)."""
    try:
        per_entry = {}
        for entry in key.get("entries", []):
            per_entry[entry["id"]] = grade_entry(entry, answer)
        scores = [r["score"] for r in per_entry.values()]
        overall = sum(scores) / max(1, len(scores))
        return {"per_entry": per_entry, "overall": overall,
                "passed": [i for i, r in per_entry.items() if r["score"] >= 1.0]}
    except Exception:
        return {"per_entry": {}, "overall": 0.0, "passed": []}


# --- verified-good excerpts (owner-checked against the real deck) ---

_GOOD_TRAP = ("Don't confuse 'visits each vertex once' (Hamilton) "
              "with 'uses each edge once' (Euler).")
_GOOD_WEIGHTED = ("Any graph whose edges have numbers attached to them is "
                  "called a weighted graph, and the numbers are called the "
                  "weights of the edges.")
_GOOD_CIRCUIT = ("Hamilton circuit: same, but returns to the starting vertex.")
_GOOD_WEIGHTS = "Cheapest links: edge AC ($119), edge BC ($121), edge AE ($133)."


def _entry(key, entry_id):
    return next(e for e in key["entries"] if e["id"] == entry_id)


def test_key_shape():
    key = load_key()
    assert key["deck"] == "AI_Lect_7_search_TSP"
    assert len(key["entries"]) == 5
    assert len({e["id"] for e in key["entries"]}) == 5


def test_grader_full_marks_on_verified_good_text():
    key = load_key()
    assert grade_entry(_entry(key, "hamilton-vs-euler"), _GOOD_TRAP)["score"] == 1.0
    assert grade_entry(_entry(key, "hamilton-path"), _GOOD_TRAP)["score"] == 1.0
    assert grade_entry(_entry(key, "weighted-graph"), _GOOD_WEIGHTED)["score"] == 1.0
    assert grade_entry(_entry(key, "hamilton-circuit"), _GOOD_CIRCUIT)["score"] == 1.0
    assert grade_entry(_entry(key, "slide-weights"), _GOOD_WEIGHTS)["score"] == 1.0


def test_grader_penalizes_degraded_text():
    key = load_key()
    entry = _entry(key, "hamilton-path")  # required: vertex, once
    assert grade_entry(entry, "A path through the graph.")["score"] == 0.0
    half = grade_entry(entry, "A path visiting each vertex.")
    assert half["score"] == 0.5
    assert half["missing"] == ["once"]


def test_grader_case_insensitive():
    key = load_key()
    entry = _entry(key, "hamilton-path")
    assert grade_entry(entry, "VERTEX visited ONCE.")["score"] == 1.0


def test_evaluate_text_overall():
    key = load_key()
    lesson = " ".join([_GOOD_TRAP, _GOOD_WEIGHTED, _GOOD_CIRCUIT, _GOOD_WEIGHTS])
    result = evaluate_text(key, lesson)
    assert result["overall"] == 1.0
    assert len(result["passed"]) == 5
    empty = evaluate_text(key, "")
    assert empty["overall"] == 0.0
    assert empty["passed"] == []
