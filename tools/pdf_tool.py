from langchain_core.tools import tool
from pypdf import PdfReader
from typing import List, Optional, Tuple

from services.context import get_current_user_id
from services.files import FileStore
from services.limits import MAX_PDF_CHARS, MAX_PDF_PAGES, MAX_UPLOAD_BYTES
from services.obs import timed as obs_timed

OCR_SCAN_PAGES: int = 5


def _resolve_reader(upload_id: str) -> Tuple[Optional[PdfReader], int, Optional[str]]:
    """Resolve an upload ID to (reader, total_pages, None) or (None, 0, STATUS=...)."""
    user_id = get_current_user_id()
    if not user_id:
        return None, 0, "STATUS=INVALID tool=read_pdf: no user context, cannot resolve uploads."
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


def _ocr_available() -> bool:
    """True only when an OCR engine is importable in this deployment."""
    try:
        import pytesseract  # noqa: F401

        return True
    except Exception:
        return False


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
                if _ocr_available():
                    return (
                        "STATUS=EMPTY tool=read_pdf: this PDF appears to be scanned "
                        f"images ({total_pages} pages, no extractable text). "
                        "On-device OCR is starting; results may be partial." + notes
                    )
                return (
                    "STATUS=EMPTY tool=read_pdf: this PDF appears to be scanned "
                    f"images ({total_pages} pages, no extractable text). "
                    "Text extraction needs a text-based PDF; image-only scans "
                    "cannot be read here (no OCR engine in this deployment)." + notes
                )
            return "STATUS=EMPTY tool=read_pdf: no extractable text." + notes
        return text + notes
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
            return (
                f"STATUS=EMPTY tool=read_pdf_page: page {page_num} has no "
                "extractable text (may be a scanned image)."
            )
        if len(text) > MAX_PDF_CHARS:
            text = text[:MAX_PDF_CHARS] + "\n[Note: page text truncated.]"
        return f"[page {page_num} of {total_pages}]\n{text}"
    except Exception as e:
        return f"STATUS=FAILED tool=read_pdf_page: {str(e)[:200]}"
