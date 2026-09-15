"""Free search chain: lite-HTML -> Wikipedia -> Wikidata -> graceful EMPTY.

All network mocked (no live calls); the live behavior was verified manually
against lite.duckduckgo.com, en.wikipedia.org, and wikidata.org.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import search_tool as st

LITE_HTML = """<html><body><table>
<tr><td>1.&nbsp;</td><td><a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fsong&amp;rut=abc" class='result-link'>Tere Liye Song</a></td></tr>
<tr><td>&nbsp;</td><td class='result-snippet'>Singers: Atif Aslam, Shreya Ghoshal</td></tr>
<tr><td>2.&nbsp;</td><td><a rel="nofollow" href="https://example.org/direct" class='result-link'>Direct Hit</a></td></tr>
</table></body></html>"""

LITE_EMPTY = "<html><body><p class='no-results'>No results</p></body></html>"

WIKI_PAYLOAD = {"query": {"search": [
    {"title": "Tere Liye (film)", "snippet": "A 2010 <span class=\"searchmatch\">film</span>."},
]}}

WIKIDATA_SEARCH = {"search": [{"id": "Q114705326", "label": "Tere Liye"}]}
WIKIDATA_ENTITIES = {"entities": {"Q114705326": {
    "labels": {"en": {"value": "Tere Liye"}},
    "claims": {
        "P175": [{"mainsnak": {"datavalue": {"type": "wikibase-entityid",
                                             "value": {"id": "Q0001"}}}}],
        "P577": [{"mainsnak": {"datavalue": {"type": "time",
                                             "value": {"time": "+2010-00-00T00:00:00Z"}}}}],
    },
    "sitelinks": {"enwiki": {"url": "https://en.wikipedia.org/wiki/Tere_Liye_(Prince_song)"}},
}}}
WIKIDATA_LABELS = {"entities": {"Q0001": {"labels": {"en": {"value": "Atif Aslam"}}}}}


class _Resp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


def _fake_urlopen(lite=LITE_HTML, wiki=WIKI_PAYLOAD, wikidata="default"):
    """Mock urlopen dispatching on host; wikidata may be a list of 3 payloads."""
    calls = []
    if wikidata == "default":
        wikidata = [WIKIDATA_SEARCH, WIKIDATA_ENTITIES, WIKIDATA_LABELS]

    def _fake(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        calls.append(url)
        if "lite.duckduckgo.com" in url:
            if isinstance(lite, Exception):
                raise lite
            return _Resp(lite.encode("utf-8"))
        if "wikipedia.org" in url:
            if isinstance(wiki, Exception):
                raise wiki
            return _Resp(json.dumps(wiki).encode("utf-8"))
        if "wikidata.org" in url:
            item = wikidata.pop(0) if isinstance(wikidata, list) else wikidata
            if isinstance(item, Exception):
                raise item
            return _Resp(json.dumps(item).encode("utf-8"))
        raise AssertionError("unexpected host: " + url)

    return _fake, calls


def _patch(monkeypatch, **kwargs):
    import urllib.request

    fake, calls = _fake_urlopen(**kwargs)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return calls


def test_lite_hit_parses_links_and_snippets(monkeypatch):
    calls = _patch(monkeypatch)
    text, sources = st.search_sources("tere liye song")
    assert len(sources) == 2
    assert sources[0]["url"] == "https://example.com/song"
    assert sources[0]["title"] == "Tere Liye Song"
    assert "Atif Aslam" in sources[0]["snippet"]
    assert sources[0]["domain"] == "example.com"
    assert sources[1]["url"] == "https://example.org/direct"
    assert "fallback" not in text
    assert not any("wikipedia.org" in c or "wikidata.org" in c for c in calls)


def test_lite_empty_falls_back_to_wikipedia(monkeypatch):
    _patch(monkeypatch, lite=LITE_EMPTY)
    text, sources = st.search_sources("tere liye song")
    assert len(sources) == 1
    assert sources[0]["url"] == "https://en.wikipedia.org/wiki/Tere_Liye_(film)"
    assert "<span" not in sources[0]["snippet"]
    assert "Wikipedia fallback" in text


def test_lite_and_wiki_empty_use_wikidata_facts(monkeypatch):
    _patch(monkeypatch, lite=LITE_EMPTY,
           wiki={"query": {"search": []}})
    text, sources = st.search_sources("tere liye song")
    assert len(sources) == 1
    assert sources[0]["url"] == "https://en.wikipedia.org/wiki/Tere_Liye_(Prince_song)"
    assert "performer: Atif Aslam" in sources[0]["snippet"]
    assert "released: 2010" in sources[0]["snippet"]
    assert "Wikidata fallback" in text


def test_all_empty_gives_graceful_empty_marker(monkeypatch):
    _patch(monkeypatch, lite=LITE_EMPTY,
           wiki={"query": {"search": []}}, wikidata={"search": []})
    text, sources = st.search_sources("zxqv-nonexistent")
    assert (text, sources) == ("", [])
    out = st.web_search.invoke({"query": "zxqv-nonexistent"})
    assert out.startswith("STATUS=EMPTY")
    assert "rephrase" not in out and "unverified" in out


def test_all_backends_down_never_raises(monkeypatch):
    down = RuntimeError("net down")
    _patch(monkeypatch, lite=down, wiki=down, wikidata=down)
    assert st.search_sources("tere liye song") == ("", [])
    out = st.web_search.invoke({"query": "tere liye song"})
    assert out.startswith("STATUS=EMPTY")
    assert st._wikipedia_search("x") == []
    assert st._wikidata_search("x") == []


def test_unwrap_ddg_redirects():
    assert st._unwrap_ddg("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=x") == "https://example.com/a"
    assert st._unwrap_ddg("//example.com/b") == "https://example.com/b"
    assert st._unwrap_ddg("https://example.com/c") == "https://example.com/c"
