"""Document embedding providers for the knowledge base.

Swappable interface; production default is Google Gemini embeddings
(free tier, same GEMINI_API_KEY as the chat tiers). Tests install the
deterministic stub via configure_embedder() — the stub is a lexical
hash baseline for shape/math tests and is explicitly NOT semantic.

Model name is env-overridable (PLUTO_KB_EMBED_MODEL) so no model
string is hardcoded into retrieval behavior.
"""

import hashlib
from typing import Callable, List, Optional

EmbedFn = Callable[[List[str]], List[List[float]]]

_embedder: Optional[EmbedFn] = None


def default_model() -> str:
    """Embedding model name (env override, sane default)."""
    from services.secrets import get_secret

    return (get_secret("PLUTO_KB_EMBED_MODEL", "") or "").strip() or "models/gemini-embedding-001"


def gemini_embed(texts: List[str]) -> List[List[float]]:
    """Embed texts with Google Gemini embeddings. Raises on missing key/failure."""
    cleaned = [str(t or "") for t in (texts or [])]
    if not cleaned:
        return []
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    from services.secrets import get_secret

    key = (get_secret("GEMINI_API_KEY", "") or "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured; document search needs it.")
    model = default_model()
    # Reuse the app's cached-client pattern (config._cached_client): the
    # client holds only model config + key, never user data, so sharing
    # one constructed instance process-wide is safe and avoids ~700ms
    # construction on every ingest/search.
    from config import _cached_client

    emb = _cached_client(
        "KB embeddings",
        0.0,
        key,
        lambda: GoogleGenerativeAIEmbeddings(model=model, google_api_key=key),
    )
    return [[float(x) for x in vec] for vec in emb.embed_documents(cleaned)]


def stub_embed(texts: List[str], dim: int = 64) -> List[List[float]]:
    """Deterministic lexical-hash vectors for tests ONLY (not semantic).

    Stable across runs (sha1, never Python hash()), L2-normalized so
    cosine math in tests is meaningful.
    """
    out: List[List[float]] = []
    for text in (texts or []):
        vec = [0.0] * dim
        for word in str(text or "").lower().split():
            bucket = int(hashlib.sha1(word.encode("utf-8")).hexdigest(), 16) % dim
            vec[bucket] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        out.append([v / norm for v in vec] if norm > 0 else vec)
    return out


def configure_embedder(fn: Optional[EmbedFn]) -> None:
    """Install a custom embedder (tests), or None to restore the default."""
    global _embedder
    _embedder = fn


def get_embedder() -> EmbedFn:
    """Return the active embedder."""
    return _embedder or gemini_embed


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a batch with the active provider (never None entries)."""
    cleaned = [str(t or "") for t in (texts or [])]
    if not cleaned:
        return []
    return get_embedder()(cleaned)
