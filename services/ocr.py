"""Shared on-device OCR helpers (leaf module, no cycles).

Extracted from services.kb and tools.pdf_tool which duplicated
_ocr_available/_ocr_image_bytes to avoid a tools/ -> services/ import
cycle (tools/__init__ pulls the whole registry). Both now import from
here: services/ never touches tools/, tools/ may import services/.
"""

import logging

logger = logging.getLogger(__name__)


def ocr_available() -> bool:
    """True only when on-device OCR can actually run (lib + binary)."""
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False
    try:
        import shutil

        return shutil.which("tesseract") is not None
    except Exception:
        logger.debug("tesseract binary check failed", exc_info=True)
        return False


def ocr_image_bytes(blob: bytes) -> str:
    """OCR one image's bytes; "" on any failure (never raises)."""
    try:
        import io as _io

        from PIL import Image
        import pytesseract

        with Image.open(_io.BytesIO(blob)) as img:
            try:
                img.load()
            except Exception:
                logger.debug("ocr image load failed", exc_info=True)
            return (pytesseract.image_to_string(img) or "").strip()
    except Exception:
        logger.debug("ocr image bytes failed", exc_info=True)
        return ""
