"""FAISS-based ANN index for Knowledge Base vector search.

Replaces brute-force linear scan with sub-millisecond ANN search.
Persists index alongside kb.json for fast startup.
"""

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import re as _re

import faiss
import numpy as np

from services.storage import data_root

logger = logging.getLogger(__name__)

_USER_RE = _re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _safe_user(user_id: str) -> str:
    text = str(user_id or "").strip()
    if not _USER_RE.match(text):
        raise ValueError("bad user id")
    return text

# Index file suffix
_INDEX_SUFFIX = ".faiss.index"

# HNSW parameters (tuned for typical KB sizes: 100-5000 chunks)
_HNSW_M = 16          # connections per node (8-48, higher = more accurate, more memory)
_HNSW_EF_CONSTRUCTION = 200  # index-time search depth (100-400)
_HNSW_EF_SEARCH = 64       # query-time search depth (16-256)

# Fallback to brute force for tiny datasets
_BRUTE_FORCE_THRESHOLD = 50


class KBIndex:
    """FAISS HNSW index for a single user's KB vectors."""

    def __init__(self, user_id: str, dim: int = 768):
        self.user_id = user_id
        self.dim = dim
        self.index_path = self._index_path(user_id)
        self.index: Optional[faiss.Index] = None
        self.id_map: Dict[int, Tuple[str, int]] = {}  # label -> (upload_id, chunk_idx)
        self.reverse_map: Dict[Tuple[str, int], int] = {}  # (upload_id, chunk_idx) -> label
        self._label_counter = 0
        self._lock = threading.RLock()
        self._load_or_create()

    def _index_path(self, user_id: str) -> Path:
        """Path to the FAISS index file for a user (no mkdir on read)."""
        safe = _safe_user(user_id)
        base = data_root() / "users" / safe
        return base / f"kb{_INDEX_SUFFIX}"

    def _load_or_create(self) -> None:
        """Load existing index or create new HNSW index."""
        with self._lock:
            if self.index_path.exists():
                try:
                    self.index = faiss.read_index(str(self.index_path))
                    # Validate stored dim; rebuild on mismatch.
                    try:
                        got = int(getattr(self.index, "d", 0) or 0)
                    except Exception:
                        got = 0
                    if got and got != self.dim:
                        logger.warning("KB index dim %s != %s; rebuilding", got, self.dim)
                        raise ValueError("dim-mismatch")
                    # Load id_map from companion JSON
                    map_path = self.index_path.with_suffix(".json")
                    if map_path.exists():
                        import json
                        with open(map_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        self.id_map = {int(k): tuple(v) for k, v in data.get("id_map", {}).items()}
                        self.reverse_map = {tuple(v): int(k) for k, v in self.id_map.items()}
                        self._label_counter = max(self.id_map.keys(), default=-1) + 1
                    logger.info("KB index loaded for %s: %d vectors", self.user_id, self.index.ntotal)
                    return
                except Exception as e:
                    logger.warning("Failed to load KB index for %s: %s; rebuilding", self.user_id, e)
                    try:
                        self._rebuild_from_kb()
                        if self.index is not None:
                            return
                    except Exception:
                        logger.debug("kb index rebuild failed", exc_info=True)

            # Create new HNSW index (Inner Product for normalized vectors = cosine similarity)
            self.index = faiss.IndexHNSWFlat(self.dim, _HNSW_M, faiss.METRIC_INNER_PRODUCT)
            self.index.hnsw.efConstruction = _HNSW_EF_CONSTRUCTION
            self.index.hnsw.efSearch = _HNSW_EF_SEARCH

    def _rebuild_from_kb(self) -> None:
        """Rebuild vectors from kb.json (used after corrupt load)."""
        try:
            from services.kb import load_kb as _load_kb
        except Exception:
            return
        try:
            kb = _load_kb(self.user_id)
        except Exception:
            return
        docs = kb.get("docs") if isinstance(kb, dict) else None
        if not isinstance(docs, dict):
            return
        self.index = faiss.IndexHNSWFlat(self.dim, _HNSW_M, faiss.METRIC_INNER_PRODUCT)
        self.index.hnsw.efConstruction = _HNSW_EF_CONSTRUCTION
        self.index.hnsw.efSearch = _HNSW_EF_SEARCH
        self.id_map = {}
        self.reverse_map = {}
        self._label_counter = 0
        for uid, doc in docs.items():
            if not isinstance(doc, dict):
                continue
            vecs = []
            for ch in doc.get("chunks") or []:
                if isinstance(ch, dict) and isinstance(ch.get("vector"), list):
                    vecs.append(ch["vector"])
            if not vecs:
                continue
            try:
                arr = np.array(vecs, dtype=np.float32)
            except Exception:
                logger.debug("kb rebuild vec convert failed", exc_info=True)
                continue
            if arr.ndim != 2 or arr.shape[1] != self.dim:
                continue
            labels = np.arange(self._label_counter, self._label_counter + len(vecs), dtype=np.int64)
            for i, label in enumerate(labels):
                self.id_map[int(label)] = (str(uid), i)
                self.reverse_map[(str(uid), i)] = int(label)
            self._label_counter += len(vecs)
            try:
                self.index.add_with_ids(arr, labels)
            except Exception:
                logger.debug("kb rebuild add failed", exc_info=True)
                continue
        self._save()

    def _save(self) -> None:
        """Persist index and id_map atomically (tmp+replace)."""
        with self._lock:
            if self.index is not None:
                try:
                    self.index_path.parent.mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass
                tmp = self.index_path.with_suffix(".tmp")
                try:
                    faiss.write_index(self.index, str(tmp))
                    os.replace(tmp, self.index_path)
                except Exception:
                    try:
                        if tmp.exists():
                            tmp.unlink()
                    except OSError:
                        pass
                    raise
                map_path = self.index_path.with_suffix(".json")
                map_tmp = self.index_path.with_suffix(".json.tmp")
                import json
                try:
                    with open(map_tmp, "w", encoding="utf-8") as f:
                        json.dump({"id_map": {str(k): list(v) for k, v in self.id_map.items()}, "dim": self.dim}, f)
                    os.replace(map_tmp, map_path)
                except Exception:
                    try:
                        if map_tmp.exists():
                            map_tmp.unlink()
                    except OSError:
                        pass

    def add_chunks(self, upload_id: str, chunks: List[Dict[str, Any]], vectors: List[List[float]]) -> None:
        """Add new chunks with their vectors to the index."""
        if not vectors:
            return
        with self._lock:
            # Detect dim drift and rebuild instead of dropping vectors.
            try:
                vec0 = len(vectors[0]) if vectors and isinstance(vectors[0], list) else 0
            except Exception:
                vec0 = 0
            if vec0 and vec0 != self.dim:
                logger.warning("KB index dim drift %s -> %s; rebuilding", self.dim, vec0)
                self.dim = int(vec0)
                self.index = faiss.IndexHNSWFlat(self.dim, _HNSW_M, faiss.METRIC_INNER_PRODUCT)
                self.index.hnsw.efConstruction = _HNSW_EF_CONSTRUCTION
                self.index.hnsw.efSearch = _HNSW_EF_SEARCH
                self.id_map = {}
                self.reverse_map = {}
                self._label_counter = 0
            # Remove any existing chunks for this upload_id (upsert semantics).
            # Deferred save: _save once at the end instead of twice per upsert.
            self.remove_document(upload_id, save=False)

            # Convert vectors to float32 array
            vecs = np.array(vectors, dtype=np.float32)
            if vecs.ndim != 2 or vecs.shape[1] != self.dim:
                logger.error("Vector dimension mismatch: expected %d, got %s", self.dim, vecs.shape)
                return

            # Assign labels
            labels = np.arange(self._label_counter, self._label_counter + len(vectors), dtype=np.int64)
            for i, label in enumerate(labels):
                self.id_map[int(label)] = (upload_id, i)
                self.reverse_map[(upload_id, i)] = int(label)
            self._label_counter += len(vectors)

            # Add to index
            self.index.add_with_ids(vecs, labels)
            self._save()

    def search(self, query_vec: List[float], k: int = 5, valid_ids: Optional[set] = None) -> List[Dict[str, Any]]:
        """Search index for top-k similar vectors.

        Returns list of dicts with upload_id, chunk_idx, score.
        """
        if self.index is None or self.index.ntotal == 0:
            return []

        with self._lock:
            k = min(k, self.index.ntotal)
            if k <= 0:
                return []

            # Search
            q = np.array([query_vec], dtype=np.float32)
            scores, labels = self.index.search(q, k * 3)  # oversample for filtering

            results = []
            for score, label in zip(scores[0], labels[0], strict=True):
                if label == -1:
                    continue
                if label not in self.id_map:
                    continue
                upload_id, chunk_idx = self.id_map[label]
                if valid_ids is not None and upload_id not in valid_ids:
                    continue
                results.append({
                    "upload_id": upload_id,
                    "chunk": chunk_idx,
                    "score": float(score),
                })
                if len(results) >= k:
                    break
            return results

    def remove_document(self, upload_id: str, save: bool = True) -> None:
        """Remove all chunks for a document from the index.

        HNSWFlat has no true deletion: native removal leaves dead vectors;
        maps are compacted here and space is reclaimed by
        rebuild_if_fragmented(). Pass save=False when the caller persists
        afterwards (e.g. add_chunks upsert saves once at the end).
        """
        with self._lock:
            # Find labels to remove
            labels_to_remove = {
                lbl for lbl, (uid, _) in self.id_map.items() if uid == upload_id
            }
            if not labels_to_remove:
                return
            # Try native removal first; always compact maps.
            try:
                if hasattr(self.index, "remove_ids"):
                    import numpy as _np

                    self.index.remove_ids(_np.array(sorted(labels_to_remove), dtype=_np.int64))
            except Exception:
                logger.debug("kb native remove failed", exc_info=True)
            # Fragmentation itself is reclaimed by rebuild_if_fragmented();
            # remove stays cheap and never rebuilds inline while holding the lock.
            for lbl in labels_to_remove:
                self.id_map.pop(lbl, None)
            # Rebuild reverse_map
            self.reverse_map = {v: k for k, v in self.id_map.items()}
            if save:
                self._save()

    def rebuild_if_fragmented(self, max_fragmentation: float = 0.3) -> None:
        """Rebuild index when native deleted count exceeds threshold."""
        with self._lock:
            try:
                ntotal = int(getattr(self.index, "ntotal", 0) or 0)
            except Exception:
                return
            live = len(self.id_map)
            if ntotal <= 0 or live <= 0:
                return
            frag = (ntotal - live) / max(1, ntotal)
            if frag < max_fragmentation:
                return
            try:
                self._rebuild_from_kb()
            except Exception:
                logger.debug("kb index defrag rebuild failed", exc_info=True)

    def get_stats(self) -> Dict[str, Any]:
        """Return index statistics."""
        with self._lock:
            # ntotal may not be immediately updated after add_with_ids; use id_map count
            actual_total = len(self.id_map)
            return {
                "total_vectors": actual_total,
                "dimension": self.dim,
                "unique_documents": len(set(uid for uid, _ in self.id_map.values())),
                "index_type": "HNSWFlat(IP)",
            }


# Global index cache per user (bounded LRU to avoid ephemeral leak)
_index_cache: Dict[str, KBIndex] = {}
_cache_lock = threading.Lock()
_INDEX_CACHE_MAX = 64


def get_index(user_id: str, dim: int = 768) -> KBIndex:
    """Get or create cached KBIndex for a user."""
    safe = _safe_user(user_id)
    with _cache_lock:
        hit = _index_cache.get(safe)
        if hit is not None:
            # Dim drift across models: rebuild rather than mis-query.
            if getattr(hit, "dim", dim) != dim:
                try:
                    del _index_cache[safe]
                except KeyError:
                    pass
            else:
                return hit
        if len(_index_cache) >= _INDEX_CACHE_MAX:
            try:
                _index_cache.pop(next(iter(_index_cache)))
            except (StopIteration, KeyError):
                pass
        idx = KBIndex(safe, dim)
        _index_cache[safe] = idx
        return idx


def invalidate_index(user_id: str) -> None:
    """Invalidate and remove cached index for a user."""
    try:
        safe = _safe_user(user_id)
    except ValueError:
        return
    with _cache_lock:
        _index_cache.pop(safe, None)


# For backward compatibility / graceful degradation
def _brute_force_search(docs: Dict[str, Any], query_vec: List[float], k: int, valid_ids: Optional[set] = None) -> List[Dict[str, Any]]:
    """Fallback brute-force search when FAISS unavailable or index empty."""
    q = np.array(query_vec, dtype=np.float32)
    scored = []
    for uid, doc in docs.items():
        if not isinstance(doc, dict):
            continue
        if valid_ids and uid not in valid_ids:
            continue
        for idx, ch in enumerate(doc.get("chunks") or []):
            if not isinstance(ch, dict):
                continue
            vec = ch.get("vector")
            if not vec:
                continue
            v = np.array(vec, dtype=np.float32)
            # Normalized vectors: IP = cosine
            score = float(np.dot(q, v))
            if score > 0:
                scored.append({"upload_id": uid, "chunk": idx, "score": score})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:k]


if __name__ == "__main__":
    # Quick smoke test
    import tempfile
    os.environ["PLUTO_DATA_DIR"] = tempfile.mkdtemp()
    idx = KBIndex("test-user", dim=8)
    # Add 3 vectors
    vecs = [
        [1.0, 0, 0, 0, 0, 0, 0, 0],
        [0, 1.0, 0, 0, 0, 0, 0, 0],
        [0.707, 0.707, 0, 0, 0, 0, 0, 0],
    ]
    chunks = [{"text": f"chunk {i}"} for i in range(3)]
    idx.add_chunks("doc1", chunks, vecs)
    # Search
    results = idx.search([0.9, 0.1, 0, 0, 0, 0, 0, 0], k=2)
    print("Search results:", results)
    # Remove
    idx.remove_document("doc1")
    print("After remove:", idx.get_stats())
