from langchain.tools import tool
from PyPDF2 import PdfReader
from typing import List

from services.context import get_current_user_id
from services.files import FileStore
from services.limits import MAX_PDF_CHARS, MAX_PDF_PAGES


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
    user_id = get_current_user_id()
    if not user_id:
        return "STATUS=INVALID tool=read_pdf: no user context, cannot resolve uploads."
    path = FileStore(user_id).resolve_upload(upload_id)
    if path is None:
        return "STATUS=DENIED tool=read_pdf: unknown upload ID or not owned by you."
    try:
        reader: PdfReader = PdfReader(str(path))
        total_pages = len(reader.pages)
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
            return "STATUS=EMPTY tool=read_pdf: no extractable text (scanned images?)." + notes
        return text + notes
    except Exception as e:
        return f"STATUS=FAILED tool=read_pdf: {str(e)[:200]}"
