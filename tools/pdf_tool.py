from langchain_core.tools import tool
from pypdf import PdfReader
import logging
from typing import List, Optional, Tuple

from services.context import get_current_user_id
from services.files import FileStore
from services.limits import MAX_PDF_CHARS, MAX_PDF_PAGES, MAX_UPLOAD_BYTES
from services.obs import timed as obs_timed
from services.ocr import ocr_available as _shared_ocr_available
from services.ocr import ocr_image_bytes as _shared_ocr_image_bytes
from tools.parse_cache import ParseCache

logger = logging.getLogger(__name__)

# ponytail: mtime-keyed parse cache — second read in same chat is RAM, not re-parse
_PDF_CACHE = ParseCache(32)

OCR_SCAN_PAGES: int = 5


def _resolve_reader(upload_id: str) -> Tuple[Optional[PdfReader], int, Optional[str]]:
    """Resolve an upload ID to (reader, total_pages, None) or (None, 0, STATUS=...)."""
    user_id = get_current_user_id()
    if not user_id:
        return None, 0, "STATUS=DENIED tool=read_pdf: no user context, cannot resolve uploads."
    path = FileStore(user_id).resolve_upload(upload_id)
    if path is None:
        return None, 0, "STATUS=DENIED tool=read_pdf: unknown upload ID or not owned by you."
    try:
        # Re-check size at read time: the file may predate current limits
        # or the registry may have been tampered with; never feed an
        # unbounded byte stream to the parser.
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            return None, 0, "STATUS=DENIED tool=read_pdf: upload exceeds the size limit."
    except OSError as e:
        return None, 0, f"STATUS=FAILED tool=read_pdf: cannot stat upload ({e})."
    try:
        reader: PdfReader = PdfReader(str(path))
        return reader, len(reader.pages), None
    except Exception as e:
        return None, 0, f"STATUS=FAILED tool=read_pdf: {str(e)[:200]}"


def _pytesseract_importable() -> bool:
    """True when the pytesseract wrapper is installed (binary not checked)."""
    try:
        import pytesseract  # noqa: F401

        return True
    except Exception:
        return False


def _tesseract_binary_present() -> bool:
    """True when the `tesseract` binary is on PATH."""
    try:
        import shutil

        return shutil.which("tesseract") is not None
    except Exception:
        return False


def _ocr_available() -> bool:
    """True only when on-device OCR can actually run (lib + binary)."""
    return _shared_ocr_available()


def _ocr_image_bytes(blob: bytes) -> str:
    """OCR one image's bytes; "" on any failure (never raises)."""
    return _shared_ocr_image_bytes(blob)


def _vision_ocr_image_bytes(blob: bytes) -> str:
    """Transcribe image bytes via a vision tier; "" when unusable (never raises)."""
    try:
        # Lazy: agent.* must not load at tools import time (import cycle
        # via agent.toolrun -> tools -> agent.vision -> agent.cascade).
        from agent.vision import vision_ocr_bytes

        return vision_ocr_bytes(blob) or ""
    except Exception:
        return ""


def _vision_ocr_configured() -> bool:
    """True when a vision-capable tier builds a client (no network call)."""
    try:
        from agent.cascade import _usable_tiers
        from services.vision import vision_supported_tier

        for name, getter in _usable_tiers(None, None):
            if not vision_supported_tier(name):
                continue
            try:
                if getter() is not None:
                    return True
            except Exception:
                logger.debug("vision tier probe failed; trying next", exc_info=True)
                continue
    except Exception:
        logger.debug("vision OCR availability check failed", exc_info=True)
    return False


def _ocr_scanned_pages(reader, total_pages: int) -> str:
    """OCR embedded page images of text-less pages (bounded, never raises).

    Scanned PDFs store each page as embedded raster images, extractable
    via pypdf without any PDF renderer or system package. Only pages
    with no native text are attempted, capped by MAX_OCR_PAGES.
    Engine: on-device tesseract when available, otherwise the free
    Gemini vision tier (verbatim transcription). Page labels name the
    engine used. Returns combined OCR text or "" when nothing usable.
    """
    try:
        from services.limits import MAX_OCR_PAGES
    except Exception:
        MAX_OCR_PAGES = 5
    try:
        pages = list(reader.pages[: min(int(MAX_OCR_PAGES or 5), int(total_pages or 0))])
    except Exception:
        return ""
    on_device = _ocr_available()
    parts: List[str] = []
    for i, page in enumerate(pages):
        try:
            if (page.extract_text() or "").strip():
                continue
        except Exception:
            logger.debug("scanned-page text probe failed", exc_info=True)
        try:
            images = list(getattr(page, "images", []) or [])
        except Exception:
            logger.debug("page image list failed; skipping page", exc_info=True)
            continue
        for img in images[:2]:
            try:
                data = getattr(img, "data", None)
                if data is None:
                    continue
                blob = bytes(data)
                if on_device:
                    text = _ocr_image_bytes(blob)
                    label = f"[page {i + 1} OCR]"
                else:
                    text = _vision_ocr_image_bytes(blob)
                    label = f"[page {i + 1} vision-OCR]"
            except Exception:
                logger.debug("page image bytes unreadable; skipping image", exc_info=True)
                continue
            if text.strip():
                parts.append(f"{label}\n{text.strip()}")
    return "\n".join(parts).strip()


def _looks_scanned(reader: PdfReader, total_pages: int) -> bool:
    """Heuristic: no extractable text on the first few pages."""
    try:
        for page in reader.pages[: min(OCR_SCAN_PAGES, total_pages)]:
            if (page.extract_text() or "").strip():
                return False
        return total_pages > 0
    except Exception:
        return False


@tool
def read_pdf(upload_id: str) -> str:
    """Read text from an uploaded PDF by its upload ID.

    Use ONLY with an upload ID the user actually provided in this
    conversation (from an attachment). Never invent IDs and never use
    filesystem paths — only opaque upload IDs are accepted.

    Args:
        upload_id: The 16-hex upload ID of a PDF owned by the user.

    Returns:
        Extracted text, or a STATUS= error marker on failure.
    """
    # ponytail: cache hit — second csv_inspect-style re-read is instant
    _hit = _PDF_CACHE.get(_PDF_CACHE.key_for(get_current_user_id(), upload_id))
    if _hit is not None:
        return _hit
    try:
        with obs_timed("pdf.parse") as rec:
            reader, total_pages, error = _resolve_reader(upload_id)
            if error is not None:
                rec["status"] = "denied" if "DENIED" in error else "failed"
                return error
        assert reader is not None
        parts: List[str] = []
        used_chars = 0
        pages_read = 0
        for i, page in enumerate(reader.pages[:MAX_PDF_PAGES]):
            chunk = page.extract_text() or ""
            if chunk.strip():
                parts.append(f"[page {i + 1}]\n{chunk}")
                used_chars += len(chunk)
            pages_read = i + 1
            if used_chars >= MAX_PDF_CHARS:
                break
        text = "\n".join(parts)
        notes: str = ""
        if total_pages > MAX_PDF_PAGES:
            notes += f"\n[Note: only the first {MAX_PDF_PAGES} of {total_pages} pages were read.]"
        elif pages_read < total_pages:
            notes += f"\n[Note: stopped after page {pages_read} at the text budget.]"
        if len(text) > MAX_PDF_CHARS:
            text = text[:MAX_PDF_CHARS]
            notes += "\n[Note: text truncated due to length.]"
        if not text.strip():
            if _looks_scanned(reader, total_pages):
                ocr_text = _ocr_scanned_pages(reader, total_pages)
                if ocr_text.strip():
                    combined = ocr_text.strip()
                    engine = "on-device OCR" if _ocr_available() else "vision-model OCR"
                    ocr_note = (f"\n[Note: text extracted via {engine} "
                                "from scanned pages — may contain errors.]")
                    if len(combined) > MAX_PDF_CHARS:
                        combined = combined[:MAX_PDF_CHARS]
                        ocr_note += " [Note: text truncated due to length.]"
                    return combined + ocr_note + notes
                if _pytesseract_importable() and not _tesseract_binary_present():
                    why = ("The OCR library is installed but the `tesseract` "
                           "binary is missing on this host, so on-device OCR "
                           "cannot run. ")
                else:
                    why = "No on-device OCR engine in this deployment. "
                if _vision_ocr_configured():
                    why += ("Vision-model OCR was attempted automatically but "
                            "returned no text (vision tiers may be cooling "
                            "down or rate-limited). ")
                else:
                    why += ("Configure a Gemini vision tier to enable "
                            "automatic vision-model OCR for scanned pages. ")
                return (
                    "STATUS=EMPTY tool=read_pdf: this PDF appears to be scanned "
                    f"images ({total_pages} pages, no extractable text). "
                    + why + notes
                )
            return "STATUS=EMPTY tool=read_pdf: no extractable text." + notes
        result = text + notes
        _PDF_CACHE.set(_PDF_CACHE.key_for(get_current_user_id(), upload_id), result)
        return result
    except Exception as e:
        return f"STATUS=FAILED tool=read_pdf: {str(e)[:200]}"


@tool
def read_pdf_page(upload_id: str, page: int) -> str:
    """Read one specific page of an uploaded PDF (1-indexed).

    Use when the user asks about a particular page ("what does page 17
    say?"). Same ownership rules as read_pdf: opaque upload IDs only.

    Args:
        upload_id: The 16-hex upload ID of a PDF owned by the user.
        page: 1-indexed page number.

    Returns:
        That page's text with its page marker, or a STATUS= error marker.
    """
    try:
        page_num = int(page)
    except Exception:
        return "STATUS=INVALID tool=read_pdf_page: page must be a number."
    try:
        with obs_timed("pdf.parse") as rec:
            reader, total_pages, error = _resolve_reader(upload_id)
            if error is not None:
                rec["status"] = "denied" if "DENIED" in error else "failed"
                return error.replace("tool=read_pdf:", "tool=read_pdf_page:", 1) \
                    if error.startswith("STATUS=") else error
        assert reader is not None
        if page_num < 1 or page_num > total_pages:
            return (
                f"STATUS=INVALID tool=read_pdf_page: page {page_num} out of range "
                f"(document has {total_pages} pages)."
            )
        if page_num > MAX_PDF_PAGES:
            return (
                f"STATUS=DENIED tool=read_pdf_page: page {page_num} is beyond "
                f"the readable limit of {MAX_PDF_PAGES} pages."
            )
        text = (reader.pages[page_num - 1].extract_text() or "").strip()
        if not text:
            if _ocr_available():
                try:
                    images = list(
                        getattr(reader.pages[page_num - 1], "images", []) or [])
                except Exception:
                    images = []
                ocr_parts = []
                for img in images[:2]:
                    try:
                        data = getattr(img, "data", None)
                        if data is None:
                            continue
                        piece = _ocr_image_bytes(bytes(data))
                    except Exception:
                        logger.debug("page image OCR failed; skipping image", exc_info=True)
                        continue
                    if piece.strip():
                        ocr_parts.append(piece.strip())
                ocr_text = "\n".join(ocr_parts).strip()
                if ocr_text:
                    if len(ocr_text) > MAX_PDF_CHARS:
                        ocr_text = ocr_text[:MAX_PDF_CHARS] + "\n[Note: page text truncated.]"
                    return (f"[page {page_num} of {total_pages}] (OCR)\n{ocr_text}"
                            "\n[Note: text extracted via on-device OCR — "
                            "may contain errors.]")
            return (
                f"STATUS=EMPTY tool=read_pdf_page: page {page_num} has no "
                "extractable text (may be a scanned image). On a Gemini "
                "vision tier, export the page as PNG/JPG and re-upload "
                "it for vision reading."
            )
        if len(text) > MAX_PDF_CHARS:
            text = text[:MAX_PDF_CHARS] + "\n[Note: page text truncated.]"
        return f"[page {page_num} of {total_pages}]\n{text}"
    except Exception as e:
        return f"STATUS=FAILED tool=read_pdf_page: {str(e)[:200]}"
