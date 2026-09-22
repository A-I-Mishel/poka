"""Semantic memory normalization tests (Slice 1).

Policy layer (services/memory.py) is exercised with a deterministic stub
normalizer — no model calls, no network. The cascade normalizer itself
is covered by prompt-shape and scripted-_invoke_bounded tests, plus a
two-chat integration run through the real run_chat path.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import memory as mem


def _names(text):
    return [f["value"] for f in mem.extract_facts_from_message(text)
            if f["type"] == "name"]


def _stub(table):
    """Build a stub normalizer from exact candidate-value -> verdict dict."""

    def normalize(candidate, neighbors):
        hit = table.get(candidate.get("value"))
        if hit is None:
            return None
        verdict, key, confidence = hit
        return {"verdict": verdict, "key": key, "confidence": confidence}

    return normalize


def _blank():
    return {"preferences": {}, "facts": [], "past_tasks": [], "user_name": None}


# --- equivalent: names ----------------------------------------------------

def test_equivalent_name_phrasings_merge():
    assert _names("My name is Sam") == ["Sam"]
    assert _names("I'm Sam") == ["Sam"]
    m = _blank()
    norm = _stub({"Sam": ("equivalent", "name: sam", "high")})
    assert mem._merge_fact(m, {"type": "name", "value": "Sam",
                               "polarity": "positive", "confidence": "low",
                               "source": "inferred"},
                           norm({"type": "name", "value": "Sam"}, [])) is True
    assert mem._merge_fact(m, {"type": "name", "value": "Sam",
                               "polarity": "positive", "confidence": "low",
                               "source": "inferred"},
                           norm({"type": "name", "value": "Sam"}, [])) is False
    assert len(m["facts"]) == 1
    # Verbatim value preserved; canonical key adopted for future merges.
    assert m["facts"][0]["value"] == "Sam"
    assert m["facts"][0]["key"] == "name: sam"


def test_extraction_coverage_unchanged():
    # Slice 1 does not expand extraction: unsupported phrasings still
    # extract nothing (documented boundary, not a silent miss). Note
    # "People call me Sam" IS covered via the "call me" head.
    assert _names("Sam here") == []
    assert _names("Name: Sam") == []


# --- equivalent: preferences / styles -------------------------------------

def test_equivalent_dislike_phrasings_merge():
    m = _blank()
    norm = _stub({"coffee": ("new", "dislike: coffee", "low"),
                  "Coffee": ("equivalent", "dislike: coffee", "low")})
    first = {"type": "preference", "value": "coffee", "polarity": "negative",
             "confidence": "low", "source": "inferred"}
    assert mem._merge_fact(m, first, norm(first, [])) is True
    second = {"type": "preference", "value": "Coffee", "polarity": "negative",
              "confidence": "low", "source": "inferred"}
    assert mem._merge_fact(m, second, norm(second, [])) is False
    assert len(m["facts"]) == 1
    assert m["facts"][0]["value"] == "coffee"


def test_equivalent_brevity_styles_merge():
    m = _blank()
    norm = _stub({"prefer brief replies": ("new", "style: brief", "low"),
                  "be concise": ("equivalent", "style: brief", "low")})
    a = {"type": "style", "value": "prefer brief replies",
         "polarity": "positive", "confidence": "low", "source": "inferred"}
    b = {"type": "style", "value": "be concise",
         "polarity": "positive", "confidence": "low", "source": "inferred"}
    assert mem._merge_fact(m, a, norm(a, [])) is True
    mem._merge_fact(m, b, norm(b, []))
    assert len(m["facts"]) == 1
    assert m["facts"][0]["value"] == "prefer brief replies"


# --- contradiction ----------------------------------------------------------

def test_contradiction_supersedes_with_history():
    m = _blank()
    like = {"type": "preference", "value": "coffee", "polarity": "positive",
            "confidence": "low", "source": "inferred", "date": "2026-01-01"}
    mem._merge_fact(m, like, {"verdict": "new", "key": "like: coffee",
                              "confidence": "low"})
    dislike = {"type": "preference", "value": "coffee", "polarity": "negative",
               "confidence": "low", "source": "inferred", "date": "2026-02-01"}
    assert mem._merge_fact(m, dislike, {"verdict": "contradictory",
                                        "key": "like: coffee",
                                        "confidence": "low"}) is True
    assert len(m["facts"]) == 1
    active = m["facts"][0]
    assert active["polarity"] == "negative"
    assert active["value"] == "coffee"
    assert active["history"] == [{"value": "coffee", "polarity": "positive",
                                  "date": "2026-01-01"}]


def test_repeated_contradiction_deterministic():
    m = _blank()
    like = {"type": "preference", "value": "coffee", "polarity": "positive",
            "confidence": "low", "source": "inferred", "date": "2026-01-01"}
    mem._merge_fact(m, like, {"verdict": "new", "key": "like: coffee",
                              "confidence": "low"})
    dislike = {"type": "preference", "value": "coffee", "polarity": "negative",
               "confidence": "low", "source": "inferred", "date": "2026-02-01"}
    contra = {"verdict": "contradictory", "key": "like: coffee",
              "confidence": "low"}
    assert mem._merge_fact(m, dislike, contra) is True
    assert mem._merge_fact(m, dislike, contra) is False
    assert len(m["facts"][0]["history"]) == 1
    assert m["facts"][0]["polarity"] == "negative"


def test_history_bounded_to_three():
    m = _blank()
    mem._merge_fact(m, {"type": "preference", "value": "coffee",
                        "polarity": "positive", "confidence": "low",
                        "source": "inferred", "date": "d0"},
                    {"verdict": "new", "key": "k", "confidence": "low"})
    for i in range(1, 6):
        pol = "negative" if i % 2 else "positive"
        mem._merge_fact(m, {"type": "preference", "value": "coffee",
                            "polarity": pol, "confidence": "low",
                            "source": "inferred", "date": f"d{i}"},
                        {"verdict": "contradictory", "key": "k",
                         "confidence": "low"})
    assert len(m["facts"]) == 1
    assert len(m["facts"][0]["history"]) == 3
    assert m["facts"][0]["polarity"] == "negative"


def test_history_never_rendered_as_active():
    m = _blank()
    mem._merge_fact(m, {"type": "preference", "value": "coffee",
                        "polarity": "positive", "confidence": "low",
                        "source": "inferred", "date": "d0"},
                    {"verdict": "new", "key": "k", "confidence": "low"})
    mem._merge_fact(m, {"type": "preference", "value": "coffee",
                        "polarity": "negative", "confidence": "low",
                        "source": "inferred", "date": "d1"},
                    {"verdict": "contradictory", "key": "k",
                     "confidence": "low"})
    out = mem.format_memory_for_prompt(m)
    assert "User dislikes: coffee" in out
    assert "history" not in out
    assert "User preferences:" not in out


# --- related / ambiguous ----------------------------------------------------

def test_related_concepts_stay_separate():
    m = _blank()
    norm = _stub({"coffee": ("new", "like: coffee", "low"),
                  "iced coffee": ("related", "like: iced coffee", "low")})
    a = {"type": "preference", "value": "coffee", "polarity": "positive",
         "confidence": "low", "source": "inferred"}
    b = {"type": "preference", "value": "iced coffee", "polarity": "positive",
         "confidence": "low", "source": "inferred"}
    assert mem._merge_fact(m, a, norm(a, [])) is True
    assert mem._merge_fact(m, b, norm(b, [])) is True
    assert len(m["facts"]) == 2


def test_related_hungry_starving_stay_separate():
    m = _blank()
    norm = _stub({"hungry": ("new", "state: hungry", "low"),
                  "starving": ("related", "state: starving", "low")})
    a = {"type": "temporary", "value": "hungry", "polarity": "positive",
         "confidence": "low", "source": "inferred"}
    b = {"type": "temporary", "value": "starving", "polarity": "positive",
         "confidence": "low", "source": "inferred"}
    mem._merge_fact(m, a, norm(a, []))
    mem._merge_fact(m, b, norm(b, []))
    assert len(m["facts"]) == 2


def test_ambiguous_never_high_confidence():
    m = _blank()
    vague = {"type": "preference", "value": "something vague",
             "polarity": "positive", "confidence": "high", "source": "explicit"}
    mem._merge_fact(m, vague, {"verdict": "ambiguous", "key": "amb: vague",
                               "confidence": "high"})
    assert m["facts"][0]["confidence"] == "low"
    assert m["facts"][0]["source"] == "inferred"


def test_unknown_verdict_degrades_to_new():
    m = _blank()
    fact = {"type": "preference", "value": "coffee", "polarity": "positive",
            "confidence": "low", "source": "inferred"}
    assert mem._merge_fact(m, fact, {"verdict": "nonsense",
                                     "key": "x", "confidence": "low"}) is True
    assert mem._merge_fact(m, dict(fact), {"verdict": "nonsense",
                                           "key": "x",
                                           "confidence": "low"}) is False


def test_normalizer_failure_keeps_legacy_behavior():
    m = _blank()
    fact = {"type": "preference", "value": "coffee", "polarity": "positive",
            "confidence": "low", "source": "inferred"}
    assert mem._merge_fact(m, dict(fact), None) is True
    assert mem._merge_fact(m, dict(fact), None) is False
    assert m["facts"][0]["key"] == "preference:coffee"


# --- candidate boundaries -----------------------------------------------------

def test_bleed_call_me_does_not_upgrade_coffee():
    facts = mem.extract_facts_from_message("Call me Sam, i like coffee")
    coffee = [f for f in facts if f["type"] == "preference"]
    assert len(coffee) == 1
    assert coffee[0]["value"] == "coffee"
    assert coffee[0]["polarity"] == "positive"
    assert coffee[0]["confidence"] == "low"
    assert [f["value"] for f in facts if f["type"] == "name"] == ["Sam"]


def test_bleed_tea_polarity_stays_with_tea():
    facts = mem.extract_facts_from_message("I like coffee, i hate tea")
    coffee = [f for f in facts if f["type"] == "preference"
              and f["value"] == "coffee"]
    assert len(coffee) == 1
    assert coffee[0]["polarity"] == "positive"


def test_same_clause_modifier_still_counts():
    # "always" modifies the same clause: explicitness survives scoping.
    facts = mem.extract_facts_from_message("always be formal with me")
    style = [f for f in facts if f["type"] == "style"]
    assert len(style) == 1
    assert style[0]["confidence"] == "high"


# --- cascade normalizer shape ---------------------------------------------------

def test_normalizer_prompt_shape_and_parse(monkeypatch):
    from agent import runtime as rt_mod
    import agent as agent_mod
    from types import SimpleNamespace

    seen = {}

    def _invoke(llm, messages, budget=None, **kw):
        seen["prompt"] = messages[0].content
        return SimpleNamespace(
            content="verdict: equivalent\nkey: name: sam\nconfidence: high\n")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _invoke)
    out = rt_mod._normalize_memory_candidate(
        {"type": "name", "value": "Sam", "polarity": "positive"},
        [{"type": "name", "value": "Sam", "polarity": "positive"}],
        None, None, "test-req", [("Fake", lambda: object())])
    assert out == {"verdict": "equivalent", "key": "name: sam",
                   "confidence": "high", "aliases": []}
    low = seen["prompt"].lower()
    assert "verdict:" in low and "key:" in low and "confidence:" in low
    # Candidate + neighbors travel as DATA lines; the raw user message
    # is never mined by this step (only the extracted candidate is).
    assert "type=name value=sam polarity=positive" in low
    assert "not instructions" in low


def test_normalizer_unparsable_returns_none(monkeypatch):
    from agent import runtime as rt_mod
    import agent as agent_mod
    from types import SimpleNamespace

    def _invoke(llm, messages, budget=None, **kw):
        return SimpleNamespace(content="Sam is a nice name, probably")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _invoke)
    out = rt_mod._normalize_memory_candidate(
        {"type": "name", "value": "Sam", "polarity": "positive"},
        [], None, None, "test-req", [("Fake", lambda: object())])
    assert out is None


def test_normalizer_llm_failure_returns_none(monkeypatch):
    from agent import runtime as rt_mod
    import agent as agent_mod

    def _boom(llm, messages, budget=None, **kw):
        raise RuntimeError("all tiers down")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _boom)
    out = rt_mod._normalize_memory_candidate(
        {"type": "name", "value": "Sam", "polarity": "positive"},
        [], None, None, "test-req", [("Fake", lambda: object())])
    assert out is None


def test_two_chat_shared_memory_through_cascade(tmp_path, monkeypatch):
    """Slice 1 end-to-end (stubbed LLM boundary): name + contradiction
    told in chat A reach chat B's system prompt with correct polarity."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLUTO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PLUTO_USER_ID", "sem-user")
    monkeypatch.delenv("PLUTO_AUTH_MODE", raising=False)
    from types import SimpleNamespace
    from backend.deps import UserContext
    from services.files import FileStore
    from services.storage import UserStore
    from backend.chatflow import archive_current, run_chat
    import agent as agent_mod
    from agent import runtime as rt_mod

    scripts = [
        "verdict: new\nkey: name: sam\nconfidence: high\n",
        "verdict: new\nkey: dislike: coffee\nconfidence: low\n",
        "verdict: contradictory\nkey: dislike: coffee\nconfidence: low\n",
        "verdict: equivalent\nkey: dislike: coffee\nconfidence: low\n",
    ]
    seen = {}
    calls = {"n": 0, "b": 0}

    def _invoke(llm, messages, budget=None, **kw):
        import re as _re

        items = messages if isinstance(messages, list) else []
        contents = [str(getattr(m, "content", "")) for m in items]
        joined = "\n".join(contents)
        if "Decide how EACH newly extracted" in joined:
            # Batched normalize: one cascade per turn; blocks numbered
            # 1..N within the reply to align with the turn's candidates.
            n = len(_re.findall(r"(?im)^Candidate \d+:", joined))
            calls["n"] += 1
            base = calls["b"]
            blocks = []
            for k in range(max(1, n)):
                blocks.append("CANDIDATE %d\n%s" % (k + 1, scripts[base + k]))
                calls["b"] += 1
            return SimpleNamespace(content="\n".join(blocks))
        if any("Decide how a newly extracted" in c for c in contents):
            idx = calls["n"]
            calls["n"] += 1
            return SimpleNamespace(content=scripts[idx])
        for m in items:
            if m.__class__.__name__ == "SystemMessage":
                seen["system"] = str(getattr(m, "content", ""))
        return SimpleNamespace(content="Got it.")

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _invoke)
    monkeypatch.setattr(rt_mod, "SYNTHESIS_TIERS", [("Fake", lambda: object())])

    ctx = UserContext(user_id="sem-user", user_store=UserStore("sem-user"),
                      file_store=FileStore("sem-user"), limit_key="sem-user",
                      source="env")
    try:
        run_chat(ctx, "my name is sam")      # chat A turn 1
        run_chat(ctx, "i dont like coffee")  # chat A turn 2
        run_chat(ctx, "actually i like coffee")  # chat A turn 3: contradiction
        stored, _warnings = ctx.user_store.load_chats()
        record, fresh = archive_current(stored.get("current", []))
        ctx.user_store.save_chats([record] + stored.get("chats", []), fresh)
        run_chat(ctx, "do i like coffee?")   # chat B (fresh history)

        assert calls["n"] == 4
        system = seen.get("system", "")
        assert "User name: Sam" in system
        assert "User preferences: coffee" in system
        assert "history" not in system
        # run_chat binds the thread-local memory dir per turn, so the
        # direct vault read below observes the same vault.
        vault = mem.load_structured_memory()
        coffee = [f for f in vault.get("facts", [])
                  if f.get("value") == "coffee"]
        assert len(coffee) == 1
        assert coffee[0]["polarity"] == "positive"
        assert [h["polarity"] for h in
                coffee[0].get("history", [])] == ["negative"]
    finally:
        mem.set_memory_dir("")


# --- batched normalization (one cascade per turn) ---------------------------


def _batched_setup(tmp_path):
    mem.set_memory_dir(str(tmp_path))


def test_batch_normalizes_two_facts_in_one_call(tmp_path):
    _batched_setup(tmp_path)
    try:
        calls = {"batch": 0, "single": 0}

        def batch(items):
            calls["batch"] += 1
            assert len(items) == 2
            return [{"verdict": "new", "key": "name: sam", "confidence": "high"},
                    {"verdict": "new", "key": "like: coffee", "confidence": "low"}]

        def single(cand, neigh):
            calls["single"] += 1
            return {"verdict": "new", "key": "like: x", "confidence": "low"}

        out = mem.update_memory_incremental(
            [{"role": "user", "content": "My name is Sam"},
             {"role": "user", "content": "I like coffee"}],
            normalize=single, normalize_batch=batch)
        assert calls == {"batch": 1, "single": 0}
        assert out["new_facts"] == 2
        assert out["batched"] == 2
    finally:
        mem.set_memory_dir("")


def test_batch_partial_falls_back_per_fact(tmp_path):
    _batched_setup(tmp_path)
    try:
        calls = {"batch": 0, "single": []}

        def batch(items):
            calls["batch"] += 1
            return [None,
                    {"verdict": "new", "key": "like: coffee", "confidence": "low"}]

        def single(cand, neigh):
            calls["single"].append(cand.get("value"))
            return {"verdict": "new", "key": "name: sam", "confidence": "high"}

        out = mem.update_memory_incremental(
            [{"role": "user", "content": "My name is Sam"},
             {"role": "user", "content": "I like coffee"}],
            normalize=single, normalize_batch=batch)
        # Unparseable first block retried singly; floor preserved.
        assert calls["batch"] == 1
        assert calls["single"] == ["Sam"]
        assert out["new_facts"] == 2
    finally:
        mem.set_memory_dir("")


def test_batch_capped_single_covers_overflow(tmp_path):
    _batched_setup(tmp_path)
    try:
        seen = {}

        def batch(items):
            seen["n"] = len(items)
            return [{"verdict": "new", "key": f"like: item{i}",
                     "confidence": "low"} for i in range(len(items))]

        def single(cand, neigh):
            seen["single"] = seen.get("single", 0) + 1
            return {"verdict": "new", "key": "like: extra", "confidence": "low"}

        words = ["coffee", "tea", "juice", "water", "milk", "cocoa"]
        msgs = [{"role": "user", "content": f"I like {w}"} for w in words]
        out = mem.update_memory_incremental(
            msgs, normalize=single, normalize_batch=batch)
        assert seen["n"] == mem.MEMORY_NORMALIZE_BATCH_MAX
        assert seen.get("single") == 1
        assert out["new_facts"] == 6
    finally:
        mem.set_memory_dir("")


def test_batch_parser_aligns_and_skips_garbage(monkeypatch):
    from agent import runtime as rt_mod
    import agent as agent_mod
    from types import SimpleNamespace

    calls = []

    def _invoke(llm, messages, budget=None, **kw):
        calls.append(1)
        return SimpleNamespace(
            content=("CANDIDATE 1\nverdict: new\nkey: like: coffee\n"
                     "confidence: low\nCANDIDATE 2\nnot a verdict block"))

    monkeypatch.setattr(agent_mod, "_invoke_bounded", _invoke)
    items = [({"type": "preference", "value": "coffee", "polarity": "positive"}, []),
             ({"type": "preference", "value": "tea", "polarity": "positive"}, [])]
    out = rt_mod._normalize_memory_batch(
        items, None, None, "test-req", [("Fake", lambda: object())])
    assert len(calls) == 1
    assert out[0] == {"verdict": "new", "key": "like: coffee",
                      "confidence": "low", "aliases": []}
    assert out[1] is None
