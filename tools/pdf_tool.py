from langchain.tools import tool
from PyPDF2 import PdfReader

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
        pages = reader.pages[:MAX_PDF_PAGES]
        text: str = ""
        for page in pages:
            text += page.extract_text() or ""
        notes: str = ""
        if total_pages > MAX_PDF_PAGES:
            notes += f"\n[Note: only the first {MAX_PDF_PAGES} of {total_pages} pages were read.]"
        if len(text) > MAX_PDF_CHARS:
            text = text[:MAX_PDF_CHARS]
            notes += "\n[Note: text truncated due to length.]"
        if not text.strip():
            return "STATUS=EMPTY tool=read_pdf: no extractable text (scanned images?)."
        return text + notes
    except Exception as e:
        return f"STATUS=FAILED tool=read_pdf: {str(e)[:200]}"
