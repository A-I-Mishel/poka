import json
import logging
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse
from langchain_core.tools import tool

from services.context import get_current_user_id, get_limit_key
from services.limits import MAX_QUERY_CHARS, MAX_SEARCH_CHARS
from services.obs import event as obs_event
from services.ratelimit import get_rate_limiter

logger: logging.Logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS: int = 5

_DDG_LITE = "https://lite.duckduckgo.com/lite/"
_WIKI_API = "https://en.wikipedia.org/w/api.php"
_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_UA = "Pluto/1.0 (research assistant)"


def _https_get(url: str, headers: Dict[str, str] | None = None, timeout: int = 15) -> bytes:
    """GET an https:// URL as bytes (raises on failure).

    Single funnel for all search backends (DDG/Wikimedia constants plus
    urlencode'd queries): the scheme is asserted so no file: or custom
    scheme can slip through, and every call carries a timeout.
    """
    import urllib.request

    if not str(url or "").lower().startswith("https://"):
        raise ValueError("refusing non-https fetch")
    req = urllib.request.Request(url, headers=headers or {"User-Agent": _UA})  # noqa: S310 (https asserted above; fixed backends)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https asserted above; fixed backends)
        # Cap reads so a compromised mirror can't OOM us with GBs.
        # Fall back to unbounded read for file-likes without size arg (tests).
        try:
            return resp.read(2 * 1024 * 1024 + 1)
        except TypeError:
            return resp.read()


def _domain_of(url: str) -> str:
    """Extract the registrable-looking host from a URL, "" when unparseable."""
    try:
        return urlparse(url).netloc.lower() or "unknown source"
    except Exception:
        return "unknown source"


def _format_sources(query: str, sources: List[Dict[str, str]]) -> str:
    """Render sources as numbered, model-readable text with markers."""
    lines: List[str] = [f'Results for "{query}":']
    for i, s in enumerate(sources, start=1):
        if s["domain"] and s["domain"] != "unknown source":
            lines.append(f"[{i}] {s['title']} — {s['domain']}")
        else:
            lines.append(f"[{i}] {s['title']}")
        if s["url"]:
            lines.append(f"URL: {s['url']}")
        if s["date"]:
            lines.append(f"Date: {s['date']}")
        if s["snippet"]:
            lines.append(f"Snippet: {s['snippet']}")
    return "\n".join(lines)


# Max results from one domain per search: Wikipedia-fallback chains
# otherwise return 5-6 same-domain chips that carry no information.
MAX_RESULTS_PER_DOMAIN: int = 2


def _cap_domains(sources: List[Dict[str, str]], limit: int = MAX_RESULTS_PER_DOMAIN) -> List[Dict[str, str]]:
    """Keep at most `limit` results per domain, order preserved (never raises)."""
    try:
        seen: Dict[str, int] = {}
        kept: List[Dict[str, str]] = []
        for s in sources or []:
            if not isinstance(s, dict):
                continue
            domain = str(s.get("domain", "") or "").lower() or "unknown source"
            if seen.get(domain, 0) >= max(1, int(limit)):
                continue
            seen[domain] = seen.get(domain, 0) + 1
            kept.append(s)
        return kept
    except Exception:
        logger.debug("domain cap failed; returning uncapped", exc_info=True)
        return list(sources or [])


# Head start for the DDG leg: a healthy DDG answer (sub-second) returns
# before Wikipedia is even started — the old sequential contract (one
# backend call) preserved exactly on the fast path. Only a slow or
# stalled DDG triggers the race.
_DDG_HEAD_START_SECONDS: float = 0.5
# Grace after the Wikipedia leg finishes while DDG is still running:
# DDG keeps its preference (fresher, multi-domain) when it answers
# promptly, but a stalled DDG no longer holds Wikipedia hostage.
_DDG_PREFERENCE_GRACE_SECONDS: float = 3.0


def _race_search_legs(query: str, max_results: int) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Run DDG-lite and Wikipedia concurrently; return (lite, wiki).

    Wall time becomes max(legs) instead of their sum: on blocked egress
    DDG burns 15s+15s of timeouts while Wikipedia already answered, so
    sequential chaining added ~30s of pure waiting per search. Daemon
    threads (never joined past need) so a stalled leg cannot block the
    caller or process exit; backends never raise (all catch internally),
    and the wrapper below treats any failure as empty. Never raises.
    """
    box: Dict[str, List[Dict[str, str]]] = {}
    done: Dict[str, bool] = {}

    def _run(key: str, fn: Any, *args: Any) -> None:
        try:
            box[key] = fn(*args)
        except Exception:
            logger.debug("search leg %s failed", key, exc_info=True)
            box[key] = []
        finally:
            done[key] = True

    try:
        import threading as _threading
        import time as _time

        lite_thread = _threading.Thread(
            target=_run, args=("lite", _ddg_lite_search, query, max_results))
        wiki_thread = _threading.Thread(
            target=_run, args=("wiki", _wikipedia_search, query, max_results))
        lite_thread.daemon = True
        wiki_thread.daemon = True
        started_at = _time.time()
        lite_thread.start()
        # Phase 1 — head start: healthy DDG answers here; Wikipedia is
        # never even called (sequential contract preserved on fast path).
        while not done.get("lite"):
            if _time.time() - started_at >= _DDG_HEAD_START_SECONDS:
                break
            _time.sleep(0.05)
        if box.get("lite"):
            return box["lite"], []
        # Phase 2 — race: DDG slow/stalled/empty; Wikipedia runs
        # concurrently. DDG keeps preference with one short grace once
        # Wikipedia is done. Each leg is bounded by its own fetch
        # timeouts; the caller's tool timeout bounds the call regardless.
        wiki_started = False
        if not done.get("lite"):
            wiki_thread.start()
            wiki_started = True
        grace_deadline: Any = None
        while not done.get("lite"):
            if done.get("wiki"):
                if grace_deadline is None:
                    grace_deadline = _time.time() + _DDG_PREFERENCE_GRACE_SECONDS
                if _time.time() >= grace_deadline:
                    break
            _time.sleep(0.05)
        if box.get("lite"):
            return box["lite"], box.get("wiki") or []
        # DDG empty/failed/slow: wait out Wikipedia (if still running)
        # and take whatever it found.
        if wiki_started:
            wiki_thread.join()
        else:
            wiki_thread.start()
            wiki_thread.join()
        return box.get("lite") or [], box.get("wiki") or []
    except Exception:
        logger.debug("search race failed; falling back sequential", exc_info=True)
        try:
            return _ddg_lite_search(query, max_results), []
        except Exception:
            return [], []


def search_sources(query: str, max_results: int = MAX_SEARCH_RESULTS) -> Tuple[str, List[Dict[str, str]]]:
    """Run a structured web search. Fully free, keyless chain (stdlib only):

    DDG-lite HTML -> Wikipedia full-text -> Wikidata entity facts.
    The first two legs race concurrently (DDG keeps preference: it wins
    whenever it returns results); Wikidata stays sequential last resort.
    Returns (formatted_text, sources); ("", []) only when every backend
    is empty or unreachable. Raises ValueError on empty query only —
    backend failures fall through, never out. Per-domain caps keep one
    backend (usually Wikipedia) from filling every chip.
    """
    query = str(query or "")[:MAX_QUERY_CHARS]
    if not query.strip():
        raise ValueError("empty query")
    lite, wiki = _race_search_legs(query, max_results)
    lite = _cap_domains(lite)
    if lite:
        return _format_sources(query, lite), lite
    wiki = _cap_domains(wiki)
    if wiki:
        return (_format_sources(query, wiki)
                + "\n[Note: results via Wikipedia fallback.]"), wiki
    facts = _cap_domains(_wikidata_search(query))
    if facts:
        return (_format_sources(query, facts)
                + "\n[Note: structured facts via Wikidata fallback.]"), facts
    return "", []


def _unwrap_ddg(href: str) -> str:
    """Unwrap DDG redirect links (//duckduckgo.com/l/?uddg=<url>&...)."""
    try:
        import urllib.parse

        href = str(href or "").strip()
        if "uddg=" in href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            real = (qs.get("uddg") or [""])[0]
            if real:
                href = real
        if href.startswith("//"):
            href = "https:" + href
        low = href.lower()
        if low.startswith(("javascript:", "data:", "vbscript:", "file:")):
            return ""
        return href
    except Exception:
        return ""


class _LiteParser(HTMLParser):
    """Extract DDG-lite result-link anchors + snippet cells. Never raises out."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: List[Dict[str, str]] = []
        self._link = False
        self._href = ""
        self._text: List[str] = []
        self._snip = False
        self._snip_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        try:
            cls = str(dict(attrs).get("class", "") or "")
        except Exception:
            cls = ""
        if tag == "a" and "result-link" in cls:
            self._link = True
            try:
                self._href = str(dict(attrs).get("href", "") or "")
            except Exception:
                self._href = ""
            self._text = []
        elif tag == "td" and "result-snippet" in cls:
            self._snip = True
            self._snip_text = []

    def handle_data(self, data: str) -> None:
        if self._link:
            self._text.append(data)
        elif self._snip:
            self._snip_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link:
            self._link = False
            url = _unwrap_ddg(self._href)
            title = "".join(self._text).strip()
            if title or url:
                self.results.append({"title": title, "url": url, "snippet": ""})
        elif tag == "td" and self._snip:
            self._snip = False
            if self.results:
                self.results[-1]["snippet"] = " ".join("".join(self._snip_text).split())


def _ddg_lite_search(query: str, max_results: int = MAX_SEARCH_RESULTS) -> List[Dict[str, str]]:
    """DDG via its lite HTML endpoint (stdlib; the API package path is dead)."""
    def _fetch(url: str) -> List[Dict[str, str]]:
        html = _https_get(
            url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"}
        ).decode("utf-8", "replace")
        parser = _LiteParser()
        parser.feed(html)
        parser.close()
        out: List[Dict[str, str]] = []
        for hit in parser.results[:max_results]:
            title, u = hit["title"].strip(), hit["url"].strip()
            if not title and not u:
                continue
            out.append({"title": title or u, "url": u,
                        "snippet": hit.get("snippet", ""), "date": "",
                        "domain": _domain_of(u)})
        return out
    try:
        import urllib.parse

        url = _DDG_LITE + "?" + urllib.parse.urlencode({"q": query})
        out = _fetch(url)
        if out:
            return out
        # ponytail: lite empty on some egress IPs (Render) — fall back to
        # html endpoint (same parser, different path) before giving up.
        try:
            html_url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
            out2 = _fetch(html_url)
            if out2:
                return out2
        except Exception:
            logger.debug("duckduckgo html fallback failed", exc_info=True)
        return out
    except Exception:
        return []


def _wiki_extracts(titles: List[str]) -> Dict[str, str]:
    """Batch-fetch plain-text extracts for titles (never raises)."""
    if not titles:
        return {}
    try:
        data = _wiki_api({
            "_endpoint": _WIKI_API, "action": "query", "prop": "extracts",
            "explaintext": "1", "exintro": "1", "titles": "|".join(titles[:10]),
            "format": "json",
        })
        pages = ((data.get("query") or {}).get("pages") or {})
        out: Dict[str, str] = {}
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            t = str(page.get("title", "") or "").strip()
            ex = str(page.get("extract", "") or "").strip()
            if t and ex:
                # Keep first ~600 chars of intro — enough for disambiguation lists.
                out[t] = re.sub(r"\s+", " ", ex)[:700]
        return out
    except Exception:
        return {}


def _wikipedia_search(query: str, max_results: int = MAX_SEARCH_RESULTS) -> List[Dict[str, str]]:
    """Keyless stdlib Wikipedia full-text fallback (no new deps). Never raises."""
    try:
        import urllib.parse
        import urllib.request

        params = urllib.parse.urlencode({
            "action": "query", "list": "search", "srsearch": query,
            "srlimit": max(1, min(int(max_results or MAX_SEARCH_RESULTS), 10)),
            "srprop": "snippet", "format": "json",
        })
        req_url = _WIKI_API + "?" + params
        data = json.loads(_https_get(req_url).decode("utf-8", "replace"))
        out: List[Dict[str, str]] = []
        hits = ((data.get("query") or {}).get("search") or [])[:max_results]
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            title = str(hit.get("title", "") or "").strip()
            if not title:
                continue
            url = ("https://en.wikipedia.org/wiki/"
                   + urllib.parse.quote(title.replace(" ", "_"), safe="/()"))
            snippet = re.sub(r"<[^>]+>", "", str(hit.get("snippet", "") or "")).strip()
            out.append({"title": title, "url": url, "snippet": snippet,
                        "date": "", "domain": "en.wikipedia.org"})
        # Enrich snippets with full intro extracts so truncated search
        # snippets (e.g., "Tere Liye may refer to: ...") don't hide the
        # Prince (2010) / Atif Aslam line the query is about.
        # ponytail: one batched extracts call only on the fallback path;
        # fail-open to snippets when offline.
        if out:
            extracts = _wiki_extracts([r["title"] for r in out])
            for r in out:
                ex = extracts.get(r["title"], "")
                # Prefer extract when it is strictly richer (contains a film/song
                # year or credit the snippet cut off). Never shorten a good snippet.
                if ex and len(ex) > len(r["snippet"]) + 20:
                    r["snippet"] = ex
            # Re-rank by query-token overlap so "tere liye song" surfaces
            # the disambiguation/Atif song page (contains "song") ahead of
            # unrelated films like "Mera Dil Tere Liye" that match only
            # "tere liye". Generic, no per-query hardcode.
            try:
                q_tokens = [t for t in re.split(r"\W+", query.lower()) if t and len(t) > 2]
                if q_tokens:
                    def _score(r: Dict[str, str]) -> int:
                        text = (r.get("title","") + " " + r.get("snippet","")).lower()
                        s = sum(1 for tok in q_tokens if tok in text)
                        # small boost for song intent when snippet is song-like
                        if "song" in q_tokens and "song" in text:
                            s += 1
                        return s
                    out.sort(key=_score, reverse=True)
            except Exception:
                logger.debug("youtube snippet scoring failed", exc_info=True)
        return out
    except Exception:
        return []


# Claim properties worth grounding (performer, composer, dates, works).
_WIKIDATA_PROPS = {
    "P175": "performer", "P86": "composer", "P676": "lyrics by",
    "P577": "released", "P361": "part of", "P57": "director",
    "P161": "cast member", "P162": "producer", "P50": "author",
}


def _wiki_api(params: Dict[str, Any]) -> Any:
    """GET a Wikimedia API endpoint as parsed JSON (raises on failure)."""
    import urllib.parse

    q = dict(params)
    url = q.pop("_endpoint", "") + "?" + urllib.parse.urlencode(q)
    return json.loads(_https_get(url).decode("utf-8", "replace"))


def _wikidata_search(query: str) -> List[Dict[str, str]]:
    """Structured entity facts (performer/composer/date/film). Never raises.

    Last-resort layer: fires only when web text backends are empty, so its
    extra calls cost nothing on the hot path. Returns up to 2 entity
    records with claim-derived fact snippets.
    """
    try:
        found = _wiki_api({"_endpoint": _WIKIDATA_API, "action": "wbsearchentities",
                           "search": query, "language": "en", "format": "json",
                           "limit": 2}).get("search", []) or []
        qids = [str(h.get("id", "")) for h in found
                if isinstance(h, dict) and str(h.get("id", "")).startswith("Q")][:2]
        if not qids:
            return []
        entities = _wiki_api({"_endpoint": _WIKIDATA_API, "action": "wbgetentities",
                              "ids": "|".join(qids), "props": "labels|claims|sitelinks",
                              "languages": "en", "format": "json"}).get("entities", {})
        # Batch-resolve value labels in one call.
        want: List[str] = []
        for qid in qids:
            claims = ((entities.get(qid) or {}).get("claims") or {})
            for prop in _WIKIDATA_PROPS:
                for claim in (claims.get(prop) or []):
                    snak = (claim.get("mainsnak") or {})
                    dv = snak.get("datavalue", {}) or {}
                    if dv.get("type") == "wikibase-entityid":
                        vid = str((dv.get("value") or {}).get("id", ""))
                        if vid.startswith("Q") and vid not in want:
                            want.append(vid)
        labels: Dict[str, str] = {}
        if want:
            got = _wiki_api({"_endpoint": _WIKIDATA_API, "action": "wbgetentities",
                             "ids": "|".join(want[:50]), "props": "labels",
                             "languages": "en", "format": "json"}).get("entities", {})
            for vid, ent in (got or {}).items():
                labels[str(vid)] = str((((ent or {}).get("labels") or {}).get("en") or {}).get("value", "") or vid)
        out: List[Dict[str, str]] = []
        for qid in qids:
            ent = entities.get(qid) or {}
            label = str(((ent.get("labels") or {}).get("en") or {}).get("value", "") or qid)
            facts: List[str] = []
            claims = ent.get("claims") or {}
            for prop, name in _WIKIDATA_PROPS.items():
                vals: List[str] = []
                for claim in (claims.get(prop) or [])[:4]:
                    dv = ((claim.get("mainsnak") or {}).get("datavalue") or {})
                    if dv.get("type") == "wikibase-entityid":
                        vid = str((dv.get("value") or {}).get("id", ""))
                        vals.append(labels.get(vid, vid))
                    elif dv.get("type") == "time":
                        vals.append(str(dv.get("value", {}).get("time", "")).lstrip("+").split("T")[0].split("-")[0])
                    elif dv.get("type") == "string":
                        vals.append(str(dv.get("value", ""))[:120])
                if vals:
                    facts.append(f"{name}: {', '.join(vals)}")
            site = ((ent.get("sitelinks") or {}).get("enwiki") or {}).get("url", "")
            url = str(site or f"https://www.wikidata.org/wiki/{qid}")
            if not facts:
                continue  # label-only entities ground nothing; skip
            snippet = f"{label} — {' ; '.join(facts[:6])}" if label and label != qid else " ; ".join(facts[:6])
            out.append({"title": label, "url": url, "snippet": snippet,
                        "date": "", "domain": _domain_of(url)})
        return out
    except Exception:
        return []


def extract_cited_sources(text: str) -> List[Dict[str, str]]:
    """Parse [n]/URL blocks back out of formatted search output.

    Only returns sources actually present in the text — nothing invented.
    """
    found: List[Dict[str, str]] = []
    blocks = re.split(r"(?m)^\[(\d+)\]\s+", text)
    # blocks[0] is preamble; then alternating (number, body) pairs.
    # re.split with one capture group always yields an even tail, so
    # strict=True documents the invariant (raises on a regex change).
    it = iter(blocks[1:])
    for number, body in zip(it, it, strict=True):
        url_match = re.search(r"(?m)^URL:\s*(\S+)", body)
        title_line = body.strip().splitlines()[0] if body.strip() else ""
        title = re.sub(r"\s+—\s+\S+\s*$", "", title_line).strip()
        url = url_match.group(1).strip() if url_match else ""
        if not title and not url:
            continue
        found.append({
            "n": number,
            "title": title or url,
            "url": url,
            "domain": _domain_of(url),
        })
    return found


@tool
def web_search(query: str) -> str:
    """Search the web (DDG-lite, Wikipedia, Wikidata — all keyless) for current information.

    Use ONLY when the user asks about events after 2024, "latest"/"recent"/
    "current" news or data, verifying an unsure factual claim, or specific
    real-world entities (companies, people, songs, movies, laws). Do NOT use for general
    knowledge, definitions, creative writing, or opinions.

    Args:
        query: Specific search query (5-10 words). Be precise.

    Returns:
        Numbered sources with titles, URLs, and snippets, or a structured
        failure marker (never silent).
    """
    query = str(query or "")[:MAX_QUERY_CHARS]
    if not query.strip():
        return "STATUS=INVALID tool=web_search: empty query."
    limit_key = get_limit_key() or get_current_user_id() or "anon"
    verdict = get_rate_limiter().check(limit_key, "search")
    if not verdict.allowed:
        obs_event(
            "ratelimit.deny", action="search", user=limit_key,
            retry_after_s=round(verdict.retry_after, 1),
        )
        return (
            "STATUS=DENIED tool=web_search: search rate limit exceeded, "
            f"retry in {verdict.retry_after:.0f}s."
        )
    try:
        formatted, _sources = search_sources(query)
        if not formatted:
            return ("STATUS=EMPTY tool=web_search: every search backend returned "
                    "no results. Answer from training knowledge instead and clearly "
                    "label entity credits as unverified — do not dead-end the user.")
        if len(formatted) > MAX_SEARCH_CHARS:
            formatted = formatted[:MAX_SEARCH_CHARS] + "\n[Note: results truncated.]"
        return formatted
    except Exception as e:
        logger.warning(f"Search failed: {e}")
        return (
            "STATUS=DEGRADED tool=web_search: web search failed "
            f"({str(e)[:150]}). This answer is NOT verified by the web; "
            "I will answer from my training knowledge instead. "
            f"Your query was: {query}"
        )
