from langchain.tools import tool
from PyPDF2 import PdfReader


@tool
def read_pdf(file_path: str) -> str:
    """Read and extract text from a PDF file.

    Args:
        file_path: Local path to the PDF file.

    Returns:
        Extracted text (truncated at 12000 chars) or an error message.
    """
    try:
        reader: PdfReader = PdfReader(file_path)
        text: str = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        if len(text) > 12000:
            text = text[:12000] + "\n...[truncated due to length]"
        if not text.strip():
            return "No text could be extracted from this PDF. It may be scanned images."
        return text
    except Exception as e:
        return f"Error reading PDF: {str(e)}"
