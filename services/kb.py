"""Per-user document knowledge base: chunk + vector retrieval.

Answers "what do my documents say" (heuristic memory answers "what has
this user told me"). Each user's chunk embeddings live in their own
vault (kb.json, atomic writes under per-file locks); retrieval is
cosine similarity over stored vectors — genuinely vector-based and
dimension-agnostic. No vector server, no native deps: JSON + math.

Untrusted content throughout: stored chunk text is DATA for prompts,
never instructions; failures degrade to "no results", never raise
into request paths (ingest/search return status, callers decide).
"""

import io
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from services import kb_embeddings
from services.limits import (
    KB_CHUNK_CHARS,
    KB_CHUNK_OVERLAP,
    KB_INGEST_EXTS,
    KB_MAX_CHUNKS_PER_DOC,
    KB_MAX_DOC_BYTES,
    KB_TOP_K,
)
from services.obs import event as obs_event
from services.storage import _read_json, _write_json, user_dir


def _kb_path(user_id: Any) -> Path:
    return user_dir(str(user_id or ""), create=False) / "kb.json"


def chunk_text(text: str, chunk_chars: int = KB_CHUNK_CHARS,
               overlap: int = KB_CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping word-boundary chunks (deterministic)."""
    words: List[str] = []
    for piece in str(text or "").split():
        if piece:
            words.append(piece)
    if not words:
        return []
    size = max(200, int(chunk_chars or KB_CHUNK_CHARS))
    ov = max(0, min(int(overlap or 0), size - 1))
    chunks: List[str] = []
    start = 0
    while start < len(words):
        acc: List[str] = []
        length = 0
        i = start
        while i < len(words) and length + len(words[i]) + 1 <= size:
            acc.append(words[i])
            length += len(words[i]) + 1
            i += 1
        if not acc:
            acc.append(words[start])
            i = start + 1
        chunks.append(" ".join(acc))
        if i >= len(words):
            break
        # Rewind by overlap worth of words (approximated in chars).
        back = 0
        back_chars = 0
        while i - 1 - back > start and back_chars < ov:
            back += 1
            back_chars += len(words[i - back]) + 1
        start = max(start + 1, i - back)
    return chunks


def cosine(a: Any, b: Any) -> float:
    """Cosine similarity; 0.0 for dim mismatch or zero vectors (never raises)."""
    try:
        fa = [float(x) for x in (a or [])]
        fb = [float(x) for x in (b or [])]
    except (TypeError, ValueError):
        return 0.0
    if not fa or len(fa) != len(fb):
        return 0.0
    dot = sum(x * y for x, y in zip(fa, fb))
    na = sum(x * x for x in fa)
    nb = sum(x * x for x in fb)
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


def _blank_kb() -> Dict[str, Any]:
    return {"version": 1, "model": "", "docs": {}}


def load_kb(user_id: Any) -> Dict[str, Any]:
    """Load a user's knowledge base; blank (never raise) when missing/corrupt."""
    try:
        data, _ = _read_json(_kb_path(user_id))
    except Exception:
        return _blank_kb()
    if not isinstance(data, dict) or not isinstance(data.get("docs"), dict):
        return _blank_kb()
    return data


def _save_kb(user_id: Any, kb: Dict[str, Any]) -> None:
    _write_json(_kb_path(user_id), kb)


def _pdf_text(blob: bytes) -> tuple:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(blob))
        parts: List[str] = []
        total = 0
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                continue
            parts.append(text)
            total += len(text)
            if total > KB_MAX_DOC_BYTES:
                break
        text = "\n".join(parts).strip()
        return (text, "") if text else ("", "empty")
    except Exception:
        return "", "pdf-extract-failed"


def extract_text(data: bytes, filename: str) -> tuple:
    """Extract indexable text from upload bytes.

    Returns (text, reason): reason is "" on success, else a short
    machine-readable marker (unsupported-type:<ext>, empty, ...).
    Only extensions in KB_INGEST_EXTS are attempted.
    """
    name = str(filename or "")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in KB_INGEST_EXTS:
        return "", "unsupported-type:%s" % (ext or "none")
    blob = bytes(data or b"")[:KB_MAX_DOC_BYTES]
    if ext == "pdf":
        return _pdf_text(blob)
    try:
        text = blob.decode("utf-8", errors="replace").strip()
    except Exception:
        return "", "decode-failed"
    return (text, "") if text else ("", "empty")


def ingest_document(user_id: Any, upload_id: Any, display_name: str, data: bytes) -> Dict[str, Any]:
    """Chunk + embed one upload into the user's vault.

    Best-effort by design (ingest must never fail an upload): every
    failure returns {"ingested": False, "reason": ...} and emits only
    metadata to obs — never document content.
    """
    uid = str(upload_id or "")
    if not uid:
        return {"ingested": False, "chunks": 0, "reason": "missing-id"}
    text, reason = extract_text(data, display_name)
    if reason or not text:
        return {"ingested": False, "chunks": 0, "reason": reason or "empty"}
    chunks = chunk_text(text)[:KB_MAX_CHUNKS_PER_DOC]
    if not chunks:
        return {"ingested": False, "chunks": 0, "reason": "empty"}
    try:
        vectors = kb_embeddings.embed_texts(chunks)
    except Exception as e:
        obs_event("kb.ingest_error", reason="embed-failed", detail=str(e)[:120])
        return {"ingested": False, "chunks": 0, "reason": "embed-failed"}
    if len(vectors) != len(chunks):
        obs_event("kb.ingest_error", reason="embed-count-mismatch")
        return {"ingested": False, "chunks": 0, "reason": "embed-count-mismatch"}
    dim = len(vectors[0]) if vectors else 0
    try:
        kb = load_kb(user_id)
        docs = kb.get("docs")
        if not isinstance(docs, dict):
            kb["docs"] = docs = {}
        docs[uid] = {
            "name": str(display_name or "file"),
            "model": kb_embeddings.default_model(),
            "dim": dim,
            "ingested_at": time.time(),
            "chunks": [{"text": c, "vector": v} for c, v in zip(chunks, vectors)],
        }
        kb["model"] = kb_embeddings.default_model()
        _save_kb(user_id, kb)
    except Exception as e:
        obs_event("kb.ingest_error", reason="store-failed", detail=str(e)[:120])
        return {"ingested": False, "chunks": 0, "reason": "store-failed"}
    return {"ingested": True, "chunks": len(chunks), "reason": ""}


def search(user_id: Any, query: Any, top_k: int = KB_TOP_K,
           valid_ids: Optional[set] = None) -> List[Dict[str, Any]]:
    """Vector search over a user's documents (never raises; [] when unusable).

    valid_ids optionally restricts to currently existing uploads, so
    pruned documents stop matching without any delete hook.
    Returns [{upload_id, name, chunk, text, score}] sorted by score desc.
    """
    q = str(query or "").strip()
    if not q:
        return []
    try:
        kb = load_kb(user_id)
        docs = kb.get("docs") or {}
        qvecs = kb_embeddings.embed_texts([q])
        if not qvecs:
            return []
        qv = qvecs[0]
        scored: List[Dict[str, Any]] = []
        for uid, doc in docs.items():
            if not isinstance(doc, dict):
                continue
            if valid_ids is not None and uid not in valid_ids:
                continue
            name = str(doc.get("name") or "document")
            for idx, ch in enumerate(doc.get("chunks") or []):
                if not isinstance(ch, dict):
                    continue
                s = cosine(qv, ch.get("vector") or [])
                if s <= 0:
                    continue
                scored.append({
                    "upload_id": uid,
                    "name": name,
                    "chunk": idx,
                    "text": str(ch.get("text") or ""),
                    "score": round(s, 4),
                })
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:max(1, int(top_k or KB_TOP_K))]
    except Exception:
        return []


def drop_document(user_id: Any, upload_id: Any) -> bool:
    """Forget one document's vectors. True when anything was removed."""
    try:
        kb = load_kb(user_id)
        docs = kb.get("docs")
        if not isinstance(docs, dict) or str(upload_id or "") not in docs:
            return False
        del docs[str(upload_id)]
        _save_kb(user_id, kb)
        return True
    except Exception:
        return False
