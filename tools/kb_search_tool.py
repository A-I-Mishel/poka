"""Document knowledge-base search: vector retrieval over user uploads.

Answers "what do my documents say" by cosine search over per-user chunk
embeddings (services.kb). Results are untrusted DATA like any tool
output; provenance (document name + score) travels with every passage.
"""

import logging

from langchain_core.tools import tool

from services import kb as kb_svc
from services.context import get_current_user_id, get_limit_key
from services.files import FileStore
from services.limits import KB_MAX_SNIPPET_CHARS, KB_TOP_K, MAX_QUERY_CHARS
from services.obs import event as obs_event
from services.ratelimit import get_rate_limiter

logger: logging.Logger = logging.getLogger(__name__)


@tool
def search_documents(query: str) -> str:
    """Search the user's uploaded documents for passages about the query.

    Use when the user asks what their documents, files, PDFs, or data
    say — or to verify a claim against uploaded material. Do NOT use
    for general knowledge, definitions, or anything not in the uploads.

    Args:
        query: Specific search query (5-10 words). Be precise.

    Returns:
        Numbered passages with document names and match scores, or a
        structured failure marker (never silent).
    """
    query = str(query or "")[:MAX_QUERY_CHARS]
    if not query.strip():
        return "STATUS=INVALID tool=search_documents: empty query."
    user_id = get_current_user_id()
    if not user_id:
        return "STATUS=DENIED tool=search_documents: no user context."
    verdict = get_rate_limiter().check(get_limit_key() or user_id, "kb_search")
    if not verdict.allowed:
        obs_event(
            "ratelimit.deny", action="kb_search", user=user_id,
            retry_after_s=round(verdict.retry_after, 1),
        )
        return (
            "STATUS=DENIED tool=search_documents: document search rate limit "
            f"exceeded, retry in {verdict.retry_after:.0f}s."
        )
    try:
        existing = {m.id for m in FileStore(user_id).list_uploads()}
    except Exception:
        logger.debug("kb_search list_uploads failed; failing closed", exc_info=True)
        return "STATUS=DEGRADED tool=search_documents: storage unavailable."
    try:
        hits = kb_svc.search(user_id, query, top_k=KB_TOP_K, valid_ids=existing)
    except Exception as e:
        logger.warning("Document search failed: %s", e)
        return "STATUS=DEGRADED tool=search_documents: document search failed."
    retried = False
    try:
        # Lite self-RAG: one score-based retry with a simplified query.
        # No extra LLM call (free-tier safe), at most two kb.search calls
        # per tool call so Gemini embed quota is bounded. Merges by
        # (upload_id, chunk) so the second pass can only add, never hide.
        if kb_svc.is_weak_result(hits, query):
            alt = kb_svc.simplified_query(query)
            if alt:
                second = kb_svc.search(user_id, alt, top_k=KB_TOP_K, valid_ids=existing)
                if second:
                    seen = {(h.get("upload_id"), h.get("chunk")) for h in (hits or [])}
                    merged = list(hits or [])
                    for h in second:
                        key = (h.get("upload_id"), h.get("chunk"))
                        if key not in seen:
                            seen.add(key)
                            merged.append(h)
                    try:
                        merged.sort(key=lambda r: float((r or {}).get("score", 0.0)), reverse=True)
                    except Exception:
                        logger.debug("kb search sort failed", exc_info=True)
                    if len(merged) > len(hits or []):
                        hits = merged[:KB_TOP_K]
                        retried = True
    except Exception:
        logger.debug("kb search merge failed", exc_info=True)
    if not hits:
        return (
            "STATUS=EMPTY tool=search_documents: no matching document passages. "
            "Only uploaded PDF/CSV documents are searchable."
        )
    lines = []
    for i, hit in enumerate(hits, 1):
        if not isinstance(hit, dict):
            continue
        text = str(hit.get("text", "") or "")
        if len(text) > 1200:
            text = text[:1200] + "…"
        try:
            score = float(hit.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        lines.append(
            f"[{i}] {str(hit.get('name', 'document'))[:200]} "
            f"(match {score:.2f}):\n{text}"
        )
    formatted = "\n\n".join(lines)
    if retried:
        formatted += "\n[Note: re-searched with simplified query.]"
    if len(formatted) > KB_MAX_SNIPPET_CHARS:
        formatted = formatted[:KB_MAX_SNIPPET_CHARS] + "\n[Note: results truncated.]"
    return formatted
