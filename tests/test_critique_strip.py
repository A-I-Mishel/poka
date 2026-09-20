"""Critique-scaffold stripping + search domain caps (Phase D).

Weak tiers sometimes emit self-critique verbatim ("Critical assessment
of the draft response" table + "Improved response (ready for user)"
rewrite) instead of answering. strip_internal_reasoning() must return
only the user-ready rewrite. Separately, one backend must not fill
every source chip (Wikipedia x6 carried no information).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.prompts import strip_internal_reasoning


CRITIQUE_LEAK = """**"Tere Liye" – Hindi song (overview and verification)**

---

### 1. Primary identification

| Item | Details | Source |
|------|---------|--------|
| Film | *Prince* (2010) | [IMDb] |

---

### 3. Critical assessment of the draft response

| Criterion | Evaluation | Comments / Corrections |
|-----------|------------|------------------------|
| Claims supported & citations | The draft listed placeholders | Added concrete citations. |
| Accuracy of genre description | Draft called Prince sci-fi | Corrected to action-thriller. |

---

### 4. Improved response (ready for user)

**"Tere Liye" – Hindi song (details)**

- **Film:** *Prince* (2010), a Hindi action-thriller
- **Singer:** Atif Aslam

*All information is drawn from publicly available, verifiable sources.*
"""


def test_critique_scaffold_returns_rewrite_only():
    out = strip_internal_reasoning(CRITIQUE_LEAK)
    assert "Critical assessment" not in out
    assert "Criterion" not in out
    assert "1. Primary identification" not in out
    assert "**\"Tere Liye\" – Hindi song (details)**" in out
    assert "Atif Aslam" in out


def test_critique_without_rewrite_untouched():
    text = "### Critical assessment\n\nSome review with no rewrite section."
    assert strip_internal_reasoning(text) == text


MISTRAL_LEAK = """Can you generate the question paper in text? Like convert the question paper in pdf again?

---
Critique of the Original Draft:

Incomplete Request Fulfillment
The user asked for two distinct actions but the draft omitted the first.
Missing Key Details
The original draft did not include the actual text of the question paper.
---

Improved Version

(Fulfills all requirements, including text conversion and PDF generation.)
---
Question Paper (Text Format - Markdown):

**i) Electric flux through a closed surface can be calculated by:**
A) Gauss' law.
---
Verification Notes:
The questions match the user's earlier options.
Recall Checkpoints:
The improved version references prior answers.
Final Note:
The original draft failed to fulfill the first request.
[PASS] only if the user confirms the markdown text matches.
"""


def test_mistral_critique_shape_returns_paper_only():
    out = strip_internal_reasoning(MISTRAL_LEAK)
    assert "Critique of the Original Draft" not in out
    assert "Incomplete Request Fulfillment" not in out
    assert "Verification Notes" not in out
    assert "Recall Checkpoints" not in out
    assert "Final Note" not in out
    assert "[PASS]" not in out
    assert "Question Paper (Text Format - Markdown)" in out
    assert "Gauss' law." in out


def test_lone_final_note_untouched():
    text = "Here is the summary.\n\nFinal Note\n\nThanks for reading!"
    assert strip_internal_reasoning(text) == text


def test_contains_critique_scaffold():
    from agent.prompts import _contains_critique_scaffold

    assert _contains_critique_scaffold(MISTRAL_LEAK) is True
    assert _contains_critique_scaffold(CRITIQUE_LEAK) is True
    assert _contains_critique_scaffold("Just a normal answer.") is False
    assert _contains_critique_scaffold(
        "### Critical assessment\n\nNo rewrite here.") is False


def test_reflection_strips_scaffolded_rewrite(monkeypatch):
    from agent import reflection as refl

    class _Resp:
        content = ("[IMPROVE]\n### Critique of the Original Draft\n\ntable\n\n"
                   "### Improved Version\n\nNew words here.")

    monkeypatch.setattr(
        "agent._invoke_bounded", lambda llm, msgs, budget=None: _Resp()
    )
    draft = "The original draft answer."
    out = refl.reflect_and_improve(object(), "req", draft, [], budget=None)
    assert "New words here." in out
    assert "Critique of the Original Draft" not in out


def test_normal_answers_untouched():
    for text in (
        "Yes. Sam Altman is the CEO of OpenAI.",
        "## Concept: Graph Basics\n**Definition**\nA graph is nodes plus edges.",
        "i) 1 ii) 2 iii) 3 iv) 4",
        " improved response times matter for latency budgets",  # inline phrase, not a heading
    ):
        assert strip_internal_reasoning(text) == text, text[:40]


def test_scaffold_still_stripped():
    text = "PLAN: think\nDELIVER: the answer"
    assert strip_internal_reasoning(text) == "the answer"


def test_search_domain_cap():
    from tools.search_tool import _cap_domains

    sources = [
        {"title": f"t{i}", "url": f"https://en.wikipedia.org/wiki/X{i}",
         "domain": "en.wikipedia.org", "snippet": "", "date": ""}
        for i in range(6)
    ]
    sources.append({"title": "imdb", "url": "https://www.imdb.com/x",
                    "domain": "www.imdb.com", "snippet": "", "date": ""})
    kept = _cap_domains(sources)
    assert sum(1 for s in kept if s["domain"] == "en.wikipedia.org") == 2
    assert kept[-1]["domain"] == "www.imdb.com"


def test_search_sources_caps_wikipedia_fallback(monkeypatch):
    import tools.search_tool as st

    monkeypatch.setattr(st, "_ddg_lite_search", lambda q, m: [])
    monkeypatch.setattr(
        st, "_wikipedia_search",
        lambda q, m: [
            {"title": f"t{i}", "url": f"https://en.wikipedia.org/wiki/X{i}",
             "domain": "en.wikipedia.org", "snippet": "", "date": ""}
            for i in range(5)
        ],
    )
    formatted, sources = st.search_sources("Tere Liye")
    assert len(sources) == 2
    assert "Wikipedia fallback" in formatted


def test_reflection_strips_critique_from_rewrite(monkeypatch):
    from agent import reflection as refl

    class _Resp:
        content = ("[IMPROVE]\n### 3. Critical assessment of the draft\n\ntable\n\n"
                   "### 4. Improved response (ready for user)\n\n"
                   + "The clean answer with full detail. " * 20)

    monkeypatch.setattr(
        "agent._invoke_bounded", lambda llm, msgs, budget=None: _Resp()
    )
    out = refl.reflect_and_improve(
        object(), "req", "A draft answer that is long enough " * 10, [],
        budget=None, task_type="research",
    )
    assert "Critical assessment" not in out
    assert "The clean answer with full detail." in out


def test_unmarked_critique_keeps_draft(monkeypatch):
    from agent import reflection as refl

    class _Resp:
        content = "### 3. Critical assessment\n\nA long critique with no marker at all. " * 5

    monkeypatch.setattr(
        "agent._invoke_bounded", lambda llm, msgs, budget=None: _Resp()
    )
    draft = "The original draft answer."
    assert refl.reflect_and_improve(object(), "req", draft, [], budget=None) == draft
