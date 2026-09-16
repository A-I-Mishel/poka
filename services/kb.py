"""Per-user document knowledge base: chunk + vector retrieval.

Answers "what do my documents say" (heuristic memory answers "what has
this user told me"). Each user's chunk embeddings live in their own
vault (kb.json, atomic writes under per-file locks); retrieval is
cosine similarity over stored vectors — genuinely vector-based and
dimension-agnostic. No vector server, no native deps: JSON + math.
Per-user totals are capped (KB_MAX_DOCS_PER_USER /
KB_MAX_TOTAL_CHUNKS_PER_USER): the whole file loads per search, so
ingest degrades to "kb-full" instead of growing it without bound.

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
    KB_MAX_DOCS_PER_USER,
    KB_MAX_TOTAL_CHUNKS_PER_USER,
    KB_TOP_K,
    KB_WEAK_LEXICAL_MIN,
    KB_WEAK_VECTOR_SCORE,
    MAX_KB_IMAGE_BYTES,
    MAX_QUERY_CHARS,
    MAX_ZIP_FILES,
    MAX_ZIP_UNCOMPRESSED_BYTES,
    MAX_ZIP_FILE_BYTES,
    MAX_ZIP_LISTED,
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


def _l2_normalize(vec: Any) -> List[float]:
    """L2-normalize a vector; input list (unmodified) for zero/empty (never raises)."""
    try:
        f = [float(x) for x in (vec or [])]
    except (TypeError, ValueError):
        return []
    if not f:
        return []
    norm = sum(x * x for x in f) ** 0.5
    if norm <= 0:
        return f
    return [x / norm for x in f]


def _dot(a: Any, b: Any) -> float:
    """Dot product over same-length vectors; 0.0 on mismatch (never raises).

    Valid score only when both inputs are L2-normalized (see _l2_normalize);
    ingest stores normalized vectors so the search hot loop skips the two
    per-chunk norm computations of cosine().
    """
    try:
        fa = [float(x) for x in (a or [])]
        fb = [float(x) for x in (b or [])]
    except (TypeError, ValueError):
        return 0.0
    if not fa or len(fa) != len(fb):
        return 0.0
    return sum(x * y for x, y in zip(fa, fb))


def _blank_kb() -> Dict[str, Any]:
    return {"version": 1, "model": "", "docs": {}}


# KB cache: user_id -> (mtime, kb_dict)
# Invalidate on mtime change or explicit write operations
_KB_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}

# ponytail: query embedding cache — second search with same query avoids Gemini RTT
_QUERY_EMBED_CACHE: Dict[tuple, List[float]] = {}
_QUERY_EMBED_LOCK = __import__("threading").Lock()
_QUERY_EMBED_MAX = 128


def load_kb(user_id: Any) -> Dict[str, Any]:
    """Load a user's knowledge base; blank (never raise) when missing/corrupt.

    Caches parsed KB by mtime for faster subsequent reads.
    """
    path = _kb_path(user_id)
    try:
        mtime = path.stat().st_mtime
        cached = _KB_CACHE.get(str(user_id))
        if cached and cached[0] == mtime:
            return cached[1]
    except OSError:
        mtime = 0.0  # File doesn't exist yet
    try:
        data, _ = _read_json(path)
    except Exception:
        kb = _blank_kb()
    else:
        if not isinstance(data, dict) or not isinstance(data.get("docs"), dict):
            kb = _blank_kb()
        else:
            kb = data
            # Update mtime from the actual file we just read
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
    _KB_CACHE[str(user_id)] = (mtime, kb)
    return kb


def invalidate_kb_cache(user_id: Any) -> None:
    """Invalidate KB cache for a user (call after write operations)."""
    _KB_CACHE.pop(str(user_id), None)


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


def _docx_text(blob: bytes) -> tuple:
    try:
        import io as _io

        from docx import Document

        doc = Document(_io.BytesIO(blob))
        parts = [(p.text or "").strip() for p in doc.paragraphs]
        parts = [p for p in parts if p]
        for table in doc.tables:
            for row in table.rows:
                cells = [(c.text or "").strip() for c in row.cells]
                line = " | ".join(c for c in cells if c)
                if line:
                    parts.append(line)
        text = "\n".join(parts).strip()
        return (text, "") if text else ("", "empty")
    except Exception:
        return "", "docx-extract-failed"


def _pptx_text(blob: bytes) -> tuple:
    try:
        import io as _io

        from pptx import Presentation

        prs = Presentation(_io.BytesIO(blob))
        parts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                try:
                    if shape.has_text_frame and shape.text:
                        text = str(shape.text).strip()
                        if text:
                            parts.append(text)
                except Exception:
                    continue
        text = "\n".join(parts).strip()
        return (text, "") if text else ("", "empty")
    except Exception:
        return "", "pptx-extract-failed"


def _xlsx_text(blob: bytes) -> tuple:
    try:
        import io as _io

        import pandas as pd

        frames = pd.read_excel(_io.BytesIO(blob), sheet_name=None, nrows=2000)
        parts = []
        items = frames.items() if isinstance(frames, dict) else [("Sheet1", frames)]
        for name, frame in items:
            try:
                parts.append(f"[{name}]\n{frame.to_string()}")
            except Exception:
                continue
        text = "\n".join(parts).strip()
        return (text, "") if text else ("", "empty")
    except Exception:
        return "", "xlsx-extract-failed"


def _ocr_available() -> bool:
    """True only when on-device image OCR can actually run (lib + binary).

    Sibling of tools.pdf_tool._ocr_available, duplicated (not imported)
    to keep services/ free of tools/ imports — tools/__init__ pulls the
    whole tool registry, which would cycle back through services.kb.
    """
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False
    try:
        import shutil

        return shutil.which("tesseract") is not None
    except Exception:
        return False


def _ocr_image_bytes(blob: bytes) -> str:
    """OCR one image's bytes; "" on any failure (never raises)."""
    try:
        import io as _io

        from PIL import Image
        import pytesseract

        with Image.open(_io.BytesIO(blob)) as img:
            try:
                img.load()
            except Exception:
                pass
            return (pytesseract.image_to_string(img) or "").strip()
    except Exception:
        return ""


def _image_text(blob: bytes, display_name: str = "") -> tuple:
    """Indexable text from an image: OCR text plus the filename header.

    Returns (text, "") on success, else ("", reason) with an honest
    machine-readable marker: image-invalid (undecodable), image-too-large
    (pixel-bomb guard), image-no-ocr (no engine on this host), empty
    (OCR ran, found nothing). Filenames are indexed alongside OCR text
    so images stay findable by name; without OCR there is nothing worth
    indexing, and ingest reports why instead of pretending.
    """
    try:
        import io as _io

        from PIL import Image

        with Image.open(_io.BytesIO(blob)) as probe:
            probe.verify()
        with Image.open(_io.BytesIO(blob)) as sized:
            width, height = sized.size
            # Same pixel gate as the vision path (services.vision).
            if width * height > 25_000_000:
                return "", "image-too-large"
    except Exception:
        return "", "image-invalid"
    if not _ocr_available():
        return "", "image-no-ocr"
    try:
        ocr = _ocr_image_bytes(blob)
    except Exception:
        return "", "image-ocr-failed"
    ocr = (ocr or "").strip()
    if not ocr:
        return "", "empty"
    name = str(display_name or "").strip()
    text = f"[image {name}]\n{ocr}".strip() if name else ocr
    return (text, "") if text else ("", "empty")


def _html_text(blob: bytes) -> tuple:
    """Strip HTML tags with stdlib only; scripts/styles are dropped."""
    import html as _html_mod
    from html.parser import HTMLParser

    if b"\x00" in blob[:8192]:
        return "", "decode-failed"
    try:
        raw = blob.decode("utf-8-sig")
    except Exception:
        try:
            raw = blob.decode("utf-8")
        except Exception:
            try:
                raw = blob.decode("latin-1")
            except Exception:
                return "", "decode-failed"

    class _Stripper(HTMLParser):
        _SKIP = frozenset({"script", "style", "noscript", "template"})
        _BLOCK = frozenset({
            "p", "div", "section", "article", "header", "footer", "main",
            "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol",
            "tr", "table", "br", "hr", "blockquote", "pre",
        })

        def __init__(self) -> None:
            super().__init__(convert_charrefs=False)
            self.parts: list[str] = []
            self.skip = 0

        def handle_starttag(self, tag: str, attrs: list) -> None:
            name = str(tag or "").lower()
            if name in self._SKIP:
                self.skip += 1
                return
            if name in self._BLOCK:
                self.parts.append("\n")

        def handle_endtag(self, tag: str) -> None:
            name = str(tag or "").lower()
            if name in self._SKIP:
                if self.skip > 0:
                    self.skip -= 1
                return
            if name in self._BLOCK:
                self.parts.append("\n")

        def handle_data(self, data: str) -> None:
            if self.skip:
                return
            if data:
                self.parts.append(data)

    try:
        parser = _Stripper()
        parser.feed(raw[:500000])
        parser.close()
        text = _html_mod.unescape("".join(parser.parts))
        lines = [" ".join(line.strip().split()) for line in text.splitlines()]
        text = "\n".join(line for line in (line.strip() for line in lines) if line).strip()
        return (text, "") if text else ("", "empty")
    except Exception:
        return "", "html-extract-failed"


def _zip_text(blob: bytes) -> tuple:
    """Indexable text from a zip: concatenated text-like members (bounded)."""
    import io as _io
    import zipfile as _zf

    try:
        zf = _zf.ZipFile(_io.BytesIO(blob))
    except Exception:
        return "", "zip-extract-failed"
    with zf:
        try:
            infos = zf.infolist()
        except Exception:
            return "", "zip-extract-failed"
        # Enforce limits from services.limits to prevent zip bombs
        if len(infos) > MAX_ZIP_FILES:
            return "", "zip-too-many-files"
        readable = {
            "txt", "md", "markdown", "log", "json", "csv", "tsv",
            "html", "htm", "xhtml", "shtml", "xml", "svg",
            "yaml", "yml", "toml", "ini", "cfg", "conf",
            "css", "scss", "less", "js", "mjs", "cjs", "jsx",
            "ts", "mts", "tsx", "py", "pyi", "java", "c", "h",
            "cpp", "hpp", "cc", "cs", "go", "rs", "php", "rb",
            "swift", "kt", "kts", "scala", "pl", "lua", "sh",
            "bash", "zsh", "bat", "cmd", "ps1", "sql", "r",
            "jl", "vue", "svelte",
        }
        parts: list[str] = []
        total = 0
        total_uncompressed = 0
        for info in infos[:MAX_ZIP_LISTED]:
            raw_name = (info.filename or "").replace("\\", "/").strip()
            if not raw_name or raw_name.endswith("/"):
                continue
            if raw_name.startswith("/") or ".." in raw_name.split("/"):
                continue
            try:
                size = int(info.file_size or 0)
            except Exception:
                size = 0
            if size <= 0 or size > MAX_ZIP_FILE_BYTES:
                continue
            total_uncompressed += size
            if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
                return "", "zip-uncompressed-too-large"
            ext = raw_name.rsplit(".", 1)[-1].lower() if "." in raw_name else ""
            if ext not in readable:
                continue
            try:
                # Read with per-file cap from limits
                member = zf.read(info.filename)[:MAX_ZIP_FILE_BYTES + 1]
            except Exception:
                continue
            if len(member) > MAX_ZIP_FILE_BYTES:
                continue
            if b"\x00" in member[:8192]:
                continue
            if ext in ("html", "htm", "xhtml", "shtml"):
                text, reason = _html_text(member)
                if reason or not text:
                    continue
            else:
                try:
                    text = member.decode("utf-8-sig").strip()
                except Exception:
                    try:
                        text = member.decode("utf-8", errors="replace").strip()
                    except Exception:
                        continue
                if not text:
                    continue
            parts.append(f"[file {raw_name}]\n{text}")
            total += len(text)
            if total > KB_MAX_DOC_BYTES:
                break
        text = "\n".join(parts).strip()
        return (text, "") if text else ("", "empty")


def _rtf_text(blob: bytes) -> tuple:
    import re as _re

    if b"\x00" in blob[:8192]:
        return "", "decode-failed"
    try:
        text = blob.decode("utf-8-sig")
    except Exception:
        try:
            text = blob.decode("utf-8", errors="replace")
        except Exception:
            return "", "decode-failed"
    if not text.lstrip().lower().startswith("{\\rtf"):
        return "", "rtf-extract-failed"
    try:
        text = _re.sub(r"\\'([0-9a-fA-F]{2})",
                        lambda m: bytes([int(m.group(1), 16)]).decode("latin-1"),
                        text)
        text = text.replace("\\par", "\n").replace("\\line", "\n").replace("\\tab", " ")
        text = _re.sub(r"\{\\\*[^}]*\}", " ", text)
        text = _re.sub(r"\\[a-zA-Z]+\d*[ ]?", " ", text)
        text = text.replace("{", " ").replace("}", " ")
        lines = [" ".join(line.strip().split()) for line in text.splitlines()]
        cleaned = "\n".join(line for line in lines if line).strip()
        return (cleaned, "") if cleaned else ("", "empty")
    except Exception:
        return "", "rtf-extract-failed"


def _ole_strings_text(blob: bytes) -> tuple:
    import re as _re

    try:
        ascii_hits = _re.findall(rb"[\x20-\x7e]{5,}", blob)
        utf16_hits = _re.findall(rb"(?:[\x20-\x7e]\x00){5,}", blob)
        seen: set[str] = set()
        kept: list[str] = []
        for hit in list(ascii_hits) + list(utf16_hits):
            try:
                piece = hit.decode("utf-16-le") if b"\x00" in hit else hit.decode("ascii")
            except Exception:
                continue
            text = " ".join(str(piece).split()).strip()
            if len(text) < 5 or text in seen:
                continue
            if " " not in text and len(text) > 80:
                continue
            seen.add(text)
            kept.append(text)
            if sum(len(k) for k in kept) > KB_MAX_DOC_BYTES:
                break
        cleaned = "\n".join(kept).strip()
        return (cleaned, "") if cleaned else ("", "empty")
    except Exception:
        return "", "ole-extract-failed"


def _odf_xml_text(blob: bytes, kind: str) -> tuple:
    import io as _io
    import zipfile as _zf
    import xml.etree.ElementTree as _ET

    try:
        with _zf.ZipFile(_io.BytesIO(blob)) as zf:
            try:
                info = zf.getinfo("content.xml")
                if int(getattr(info, "file_size", 0) or 0) > KB_MAX_DOC_BYTES:
                    return "", f"{kind}-extract-failed"
            except KeyError:
                return "", f"{kind}-extract-failed"
            content = zf.read("content.xml")
    except Exception:
        return "", f"{kind}-extract-failed"
    if len(content) > KB_MAX_DOC_BYTES:
        return "", f"{kind}-extract-failed"
    # XXE / billion-laughs: reject entity declarations before parsing
    low = content.lower()
    if b"<!doctype" in low or b"<!entity" in low:
        return "", f"{kind}-extract-failed"
    try:
        try:
            import defusedxml.ElementTree as _DET  # type: ignore

            root = _DET.fromstring(content, forbid_dtd=True, forbid_entities=True)
        except ImportError:
            root = _ET.fromstring(content)
    except Exception:
        return "", f"{kind}-extract-failed"
    ns = {
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
        "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
        "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    }
    try:
        if kind == "odt":
            parts = [" ".join("".join(e.itertext()).split()).strip()
                     for e in root.iter()
                     if str(e.tag or "") in (
                         f"{{{ns['text']}}}p", f"{{{ns['text']}}}h")]
            text = "\n".join(p for p in parts if p).strip()
        elif kind == "ods":
            parts = []
            for table in root.iter(f"{{{ns['table']}}}table"):
                name = table.get(f"{{{ns['table']}}}name", "Sheet")
                parts.append(f"[{name}]")
                for row in table.iter(f"{{{ns['table']}}}table-row"):
                    cells = [" ".join("".join(c.itertext()).split())
                             for c in row.iter(f"{{{ns['table']}}}table-cell")]
                    line = " | ".join(c for c in cells if c)
                    if line:
                        parts.append(line)
            text = "\n".join(parts).strip()
        else:
            parts = []
            pages = list(root.iter(f"{{{ns['draw']}}}page"))
            for i, page in enumerate(pages, start=1):
                lines = [" ".join("".join(e.itertext()).split()).strip()
                         for e in page.iter()
                         if str(e.tag or "") in (
                             f"{{{ns['text']}}}p", f"{{{ns['text']}}}h")]
                lines = [line for line in lines if line]
                if lines:
                    parts.append(f"[slide {i}]\n" + "\n".join(lines))
            text = "\n".join(parts).strip()
        return (text, "") if text else ("", "empty")
    except Exception:
        return "", f"{kind}-extract-failed"


def _xls_text(blob: bytes) -> tuple:
    try:
        import io as _io

        import pandas as pd

        try:
            frames = pd.read_excel(_io.BytesIO(blob), sheet_name=None,
                                   engine="xlrd", nrows=2000)
        except Exception:
            frames = None
        if frames is not None:
            parts = []
            items = frames.items() if isinstance(frames, dict) else [("Sheet1", frames)]
            for name, frame in items:
                try:
                    parts.append(f"[{name}]\n{frame.to_string()}")
                except Exception:
                    continue
            text = "\n".join(parts).strip()
            if text:
                return text, ""
    except Exception:
        pass
    return _ole_strings_text(blob)


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
    if ext in ("png", "jpg", "jpeg", "webp", "gif", "bmp"):
        # Images need whole-file bytes (a 400 KB-truncated image is
        # undecodable); capped separately by MAX_KB_IMAGE_BYTES.
        return _image_text(bytes(data or b"")[:MAX_KB_IMAGE_BYTES], name)
    blob = bytes(data or b"")[:KB_MAX_DOC_BYTES]
    if ext == "pdf":
        return _pdf_text(blob)
    if ext == "docx":
        return _docx_text(blob)
    if ext == "pptx":
        return _pptx_text(blob)
    if ext == "xlsx":
        return _xlsx_text(blob)
    if ext in ("html", "htm", "xhtml", "shtml"):
        return _html_text(blob)
    if ext == "zip":
        return _zip_text(blob)
    if ext == "rtf":
        return _rtf_text(blob)
    if ext in ("doc", "ppt"):
        return _ole_strings_text(blob)
    if ext == "xls":
        return _xls_text(blob)
    if ext in ("odt", "ods", "odp"):
        return _odf_xml_text(blob, ext)
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
    chunks = chunk_text(text)
    if not chunks:
        return {"ingested": False, "chunks": 0, "reason": "empty"}
    if len(chunks) > KB_MAX_CHUNKS_PER_DOC:
        obs_event("kb.ingest_error", reason="doc-chunks-exceed", detail=f"chunks={len(chunks)} cap={KB_MAX_CHUNKS_PER_DOC}")
        chunks = chunks[:KB_MAX_CHUNKS_PER_DOC]
    # Growth + embedding-model guard (checked BEFORE spending embedding
    # quota): fail open to no cap when the vault is unreadable — the
    # store step below still reports store-failed honestly. Mixing
    # chunks from two embedding models would silently orphan the old
    # ones (dim mismatch score 0), so refuse clearly instead.
    from services.storage import path_lock
    lock_path = _kb_path(user_id)
    with path_lock(lock_path):
        try:
            kb_now = load_kb(user_id)
            existing = kb_now.get("docs") or {}
            if not isinstance(existing, dict):
                existing = {}
            cur_model = kb_embeddings.default_model()
            vault_model = str(kb_now.get("model") or "")
            if vault_model and vault_model != cur_model:
                obs_event("kb.ingest_error", reason="embed-model-changed")
                return {"ingested": False, "chunks": 0, "reason": "embed-model-changed"}
            if uid not in existing and len(existing) >= KB_MAX_DOCS_PER_USER:
                obs_event("kb.ingest_error", reason="kb-full")
                return {"ingested": False, "chunks": 0, "reason": "kb-full"}
            total = sum(
                len(d.get("chunks") or [])
                for d in existing.values() if isinstance(d, dict)
            )
            old = existing.get(uid)
            old_count = len(old.get("chunks") or []) if isinstance(old, dict) else 0
            if total - old_count + len(chunks) > KB_MAX_TOTAL_CHUNKS_PER_USER:
                obs_event("kb.ingest_error", reason="kb-full")
                return {"ingested": False, "chunks": 0, "reason": "kb-full"}
        except Exception:
            # If vault unreadable, skip cap checks but still attempt store (will fail there)
            pass
    try:
        vectors = kb_embeddings.embed_texts(chunks)
    except Exception as e:
        obs_event("kb.ingest_error", reason="embed-failed", detail=str(e)[:120])
        return {"ingested": False, "chunks": 0, "reason": "embed-failed"}
    if len(vectors) != len(chunks):
        obs_event("kb.ingest_error", reason="embed-count-mismatch")
        return {"ingested": False, "chunks": 0, "reason": "embed-count-mismatch"}
    dim = len(vectors[0]) if vectors else 0
    if dim <= 0 or any(len(v) != dim for v in vectors):
        obs_event("kb.ingest_error", reason="embed-dim-mismatch")
        return {"ingested": False, "chunks": 0, "reason": "embed-dim-mismatch"}
    # Store L2-normalized vectors so search becomes a plain dot product
    # (old vaults without "normalized" still fall back to cosine()).
    stored_vectors: List[List[float]] = []
    for v in vectors:
        nv = _l2_normalize(v)
        # Validate: no NaN/inf in normalized vectors
        if any(not isinstance(x, (int, float)) or x != x or x == float('inf') or x == float('-inf') for x in nv):
            obs_event("kb.ingest_error", reason="embed-nan-inf")
            return {"ingested": False, "chunks": 0, "reason": "embed-nan-inf"}
        stored_vectors.append(nv)
    try:
        from services.storage import path_lock
        lock_path = _kb_path(user_id)
        with path_lock(lock_path):
            kb = load_kb(user_id)
            docs = kb.get("docs")
            if not isinstance(docs, dict):
                kb["docs"] = docs = {}
            docs[uid] = {
                "name": str(display_name or "file"),
                "model": kb_embeddings.default_model(),
                "dim": dim,
                "normalized": True,
                "ingested_at": time.time(),
                "chunks": [{"text": c, "vector": v} for c, v in zip(chunks, stored_vectors)],
            }
            kb["model"] = kb_embeddings.default_model()
            _save_kb(user_id, kb)
            invalidate_kb_cache(user_id)
            # Update FAISS index
            try:
                from services.kb_index import get_index
                index = get_index(str(user_id), dim=dim)
                # Prepare chunks for index (just need upload_id and chunk index)
                index_chunks = [{"text": c} for c in chunks]
                index.add_chunks(uid, index_chunks, stored_vectors)
            except Exception as e:
                obs_event("kb.ingest_warn", reason="faiss_index_failed", detail=str(e)[:120])
    except Exception:
        # Avoid leaking exception detail that may contain secrets
        obs_event("kb.ingest_error", reason="store-failed")
        return {"ingested": False, "chunks": 0, "reason": "store-failed"}
    return {"ingested": True, "chunks": len(chunks), "reason": ""}


def _lexical_search(docs: Dict[str, Any], query: str, valid_ids: Optional[set] = None) -> List[Dict[str, Any]]:
    """Term-overlap fallback when embeddings are unavailable (never raises).

    Labeled plainly: this is lexical (keyword) retrieval, not semantic;
    it lets KB search degrade to useful results during a Gemini 429
    window instead of returning nothing.
    """
    import re as _re

    tokens = set(_re.findall(r"[a-z0-9]+", query.lower()))
    if not tokens:
        return []
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
            text = str(ch.get("text") or "")
            overlap = len(tokens & set(_re.findall(r"[a-z0-9]+", text.lower())))
            if overlap <= 0:
                continue
            scored.append({
                "upload_id": uid,
                "name": name,
                "chunk": idx,
                "text": text,
                "score": round(float(overlap), 4),
            })
    return scored


_SELF_RAG_STOPWORDS = frozenset({
    "what", "do", "does", "did", "my", "our", "your", "the", "a", "an",
    "about", "say", "says", "said", "in", "on", "of", "for", "to",
    "is", "are", "was", "were", "be", "and", "or", "any", "find",
    "search", "show", "tell", "me", "please", "documents", "files",
    "file", "document",
})


def simplified_query(query: Any) -> str:
    """Small keyword query for the one lite self-RAG retry (no LLM).

    Drops stopwords so "what do my documents say about plato" becomes
    "plato". Never raises; "" means "no useful simplification".
    """
    import re as _re

    try:
        tokens = _re.findall(r"[a-z0-9]+", str(query or "").lower())
    except Exception:
        return ""
    kept = [t for t in tokens if t not in _SELF_RAG_STOPWORDS and len(t) > 1]
    out = " ".join(kept).strip()
    if not out or out == str(query or "").strip().lower():
        return ""
    return out[:MAX_QUERY_CHARS]


def is_weak_result(hits: Any, query: Any) -> bool:
    """True when a first-pass KB result deserves one retry (no LLM).

    Weak = empty, or top hit below threshold: vector cosine scores live
    0..1 (weak below KB_WEAK_VECTOR_SCORE); lexical scores are integer
    term-overlap counts (weak below KB_WEAK_LEXICAL_MIN). Short queries
    (<=2 tokens) never retry — there is nothing to simplify.
    """
    import re as _re

    try:
        items = list(hits or [])
    except Exception:
        return True
    if not items:
        return True
    try:
        qtokens = _re.findall(r"[a-z0-9]+", str(query or "").lower())
    except Exception:
        qtokens = []
    if len(qtokens) <= 2:
        return False
    try:
        top = float((items[0] or {}).get("score", 0.0))
    except Exception:
        return True
    if top >= 1.0:
        # Lexical overlap counts (1, 2, ...) and a perfect vector 1.0
        # collide here; favor recall (one bounded retry) over saving one
        # embed call — a spurious retry only merges, never hides.
        return top < float(KB_WEAK_LEXICAL_MIN)
    return top < float(KB_WEAK_VECTOR_SCORE)


def search(user_id: Any, query: Any, top_k: int = KB_TOP_K,
           valid_ids: Optional[set] = None) -> List[Dict[str, Any]]:
    """Vector search over a user's documents (never raises; [] when unusable).

    valid_ids optionally restricts to currently existing uploads, so
    pruned documents stop matching without any delete hook.
    Returns [{upload_id, name, chunk, text, score}] sorted by score desc.
    Re-scoring embeddings hitting a rate limit degrades to lexical
    term-overlap search (emits obs metadata), never an empty failure.

    Uses FAISS HNSW index for sub-millisecond ANN search when available.
    """
    q = str(query or "").strip()
    if not q:
        return []
    try:
        kb = load_kb(user_id)
        docs = kb.get("docs") or {}
        if not isinstance(docs, dict):
            docs = {}
    except Exception as e:
        obs_event("kb.search_error", reason="load", detail=str(e)[:120])
        return []
    qv: List[float] = []
    try:
        # ponytail: query embed cache — second identical search avoids Gemini call
        qkey = (q.strip().lower(), kb_embeddings.default_model())
        with _QUERY_EMBED_LOCK:
            hit = _QUERY_EMBED_CACHE.get(qkey)
        if hit is not None:
            qv = hit
        else:
            qvecs = kb_embeddings.embed_texts([q])
            if qvecs:
                qv = _l2_normalize(qvecs[0])
                with _QUERY_EMBED_LOCK:
                    if len(_QUERY_EMBED_CACHE) >= _QUERY_EMBED_MAX:
                        _QUERY_EMBED_CACHE.pop(next(iter(_QUERY_EMBED_CACHE)))
                    _QUERY_EMBED_CACHE[qkey] = qv
    except Exception:
        # Avoid leaking exception detail that may contain secrets
        obs_event("kb.search_error", reason="embed")
    # Validate top_k to prevent DoS/unbounded slice
    try:
        k = int(top_k or KB_TOP_K)
    except (TypeError, ValueError):
        k = KB_TOP_K
    k = max(1, min(k, KB_TOP_K))

    # Try FAISS index first for fast ANN search
    if qv:
        try:
            from services.kb_index import get_index
            index = get_index(str(user_id))
            if index.index is not None and index.index.ntotal > 0:
                # Fast ANN search
                ann_results = index.search(qv, k=k, valid_ids=valid_ids)
                if ann_results:
                    # Enrich with document name and text from kb
                    enriched = []
                    for r in ann_results:
                        uid = r["upload_id"]
                        chunk_idx = r["chunk"]
                        doc = docs.get(uid)
                        if not isinstance(doc, dict):
                            continue
                        ch = (doc.get("chunks") or [])[chunk_idx] if chunk_idx < len(doc.get("chunks") or []) else None
                        if not isinstance(ch, dict):
                            continue
                        enriched.append({
                            "upload_id": uid,
                            "name": str(doc.get("name") or "document"),
                            "chunk": chunk_idx,
                            "text": str(ch.get("text") or ""),
                            "score": round(r["score"], 4),
                        })
                    return enriched
        except Exception as e:
            obs_event("kb.search_warn", reason="faiss_fallback", detail=str(e)[:120])
            # Fall through to brute force

    # Fallback: brute-force search (original behavior)
    if qv:
        scored: List[Dict[str, Any]] = []
        for uid, doc in docs.items():
            if not isinstance(doc, dict):
                continue
            if valid_ids is not None and uid not in valid_ids:
                continue
            normalized = bool(doc.get("normalized"))
            name = str(doc.get("name") or "document")
            for idx, ch in enumerate(doc.get("chunks") or []):
                if not isinstance(ch, dict):
                    continue
                vec = ch.get("vector") or []
                s = _dot(qv, vec) if normalized else cosine(qv, vec)
                if s <= 0 or s != s:
                    continue
                scored.append({
                    "upload_id": uid,
                    "name": name,
                    "chunk": idx,
                    "text": str(ch.get("text") or ""),
                    "score": round(s, 4),
                })
    else:
        scored = _lexical_search(docs, q, valid_ids)
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:k]


def drop_document(user_id: Any, upload_id: Any) -> bool:
    """Forget one document's vectors. True when anything was removed."""
    try:
        kb = load_kb(user_id)
        docs = kb.get("docs")
        if not isinstance(docs, dict) or str(upload_id or "") not in docs:
            return False
        del docs[str(upload_id)]
        _save_kb(user_id, kb)
        invalidate_kb_cache(user_id)
        # Remove from FAISS index
        try:
            from services.kb_index import get_index
            index = get_index(str(user_id))
            index.remove_document(str(upload_id))
        except Exception:
            pass
        return True
    except Exception:
        return False
