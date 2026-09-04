import uuid
from langchain.tools import tool
from docx import Document


@tool
def create_docx(title: str, content: str) -> str:
    """Create a Word document with title and body content.

    Args:
        title: Document heading.
        content: Body text; each newline-separated line becomes a paragraph.

    Returns:
        Filename of the saved document.
    """
    try:
        doc: Document = Document()
        doc.add_heading(title, level=1)
        for paragraph in content.strip().split("\n"):
            if paragraph.strip():
                doc.add_paragraph(paragraph.strip())
        filename: str = f"docx_{uuid.uuid4().hex[:8]}.docx"
        doc.save(filename)
        return f"Document saved as {filename}"
    except Exception as e:
        return f"Error creating document: {str(e)}"
