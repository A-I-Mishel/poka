"""Search-backend race: wall time becomes max(legs), not their sum.

Measured baseline (sequential): two stalled DDG backends at 2s each +
 Wikipedia ~= 4s+ for one search; production timeouts (15s x2) make it
 ~30s+ before Wikipedia even starts. The race runs DDG-lite and
 Wikipedia concurrently: DDG keeps preference (wins whenever it returns
 results), Wikipedia is taken after one short grace when DDG stalls.
 Wikidata stays sequential last resort. No source contract changes.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tools.search_tool as st


def _stalling_http(block_hosts=("duckduckgo",), stall=2.0):
    real = st._https_get

    def _fake(url, headers=None, timeout=15):
        if any(h in (url or "") for h in block_hosts):
            time.sleep(stall)
            raise OSError("blocked egress")
        return real(url, headers=headers, timeout=timeout)

    return _fake


def test_blocked_egress_takes_wiki_after_grace(monkeypatch):
    monkeypatch.setattr(st, "_https_get", _stalling_http())
    t0 = time.perf_counter()
    text, sources = st.search_sources("Tere Liye song")
    dt = time.perf_counter() - t0
    assert sources, "wikipedia fallback must still answer"
    assert all(s["domain"] == "en.wikipedia.org" for s in sources)
    assert "Wikipedia fallback" in text
    # Sequential would cost 2x stall + wiki (~4s+ here, ~30s+ in prod);
    # the race costs stall-of-one-leg + grace + wiki-overlap.
    assert dt < 2 * 2.0 + st._DDG_PREFERENCE_GRACE_SECONDS + 2.5, dt


def test_ddg_preference_preserved(monkeypatch):
    def _fast(url, headers=None, timeout=15):
        if "duckduckgo" in (url or ""):
            return (b'<html><body><a class="result-link" '
                    b'href="https://example.com/song">Example Song</a>'
                    b'<td class="result-snippet">A song snippet</td>'
                    b'</body></html>')
        raise OSError("wiki down for this test")

    monkeypatch.setattr(st, "_https_get", _fast)
    text, sources = st.search_sources("Example Song")
    assert sources and sources[0]["url"] == "https://example.com/song"
    assert "Wikipedia fallback" not in text


def test_both_dead_returns_empty(monkeypatch):
    def _dead(url, headers=None, timeout=15):
        raise OSError("offline")

    monkeypatch.setattr(st, "_https_get", _dead)
    assert st.search_sources("anything at all") == ("", [])


def test_empty_query_still_raises():
    import pytest

    with pytest.raises(ValueError):
        st.search_sources("   ")
