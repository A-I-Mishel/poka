import io
import uuid
from langchain.tools import tool
from docx import Document

from services.context import get_current_user_id
from services.files import FileStore
from services.ratelimit import get_rate_limiter
from services.storage import StorageError


@tool
def create_docx(title: str, content: str) -> str:
    """Create a Word document (.docx file).

    Use ONLY when the user explicitly asks for a document, essay, report,
    resume, or Word file. Do NOT use for chat responses, quick answers,
    or when the user just wants information.

    Args:
        title: Document heading.
        content: Body text; each newline-separated line becomes a paragraph.

    Returns:
        Filename of the saved document (plus its download ID).
    """
    try:
        doc: Document = Document()
        doc.add_heading(title, level=1)
        for paragraph in content.strip().split("\n"):
            if paragraph.strip():
                doc.add_paragraph(paragraph.strip())
        filename: str = f"docx_{uuid.uuid4().hex[:8]}.docx"
        buf = io.BytesIO()
        doc.save(buf)
        data: bytes = buf.getvalue()

        user_id = get_current_user_id()
        if user_id:
            verdict = get_rate_limiter().check(user_id, "generate")
            if not verdict.allowed:
                return (
                    "STATUS=DENIED tool=create_docx: generation rate limit "
                    f"exceeded, retry in {verdict.retry_after:.0f}s."
                )
            try:
                meta = FileStore(user_id).register_output(filename, data, "docx")
                return f"Document saved as {meta.display_name} (file ID: {meta.id})"
            except StorageError as e:
                return f"STATUS=FAILED tool=create_docx: {e}"
        with open(filename, "wb") as f:
            f.write(data)
        return f"Document saved as {filename}"
    except Exception as e:
        return f"STATUS=FAILED tool=create_docx: {str(e)}"
