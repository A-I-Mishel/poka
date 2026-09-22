"""Shared embedded-picture handling for .pptx readers (leaf module).

Photographed/text-bearing pictures inside decks are invisible to the
text-frame walkers, so image-only slides extract as nothing on every
model, vision or not. This module finds pictures in slide order and
renders them as text lines:

* author-written alt text first (zero quota, works everywhere);
* on-device OCR text when alt text is absent (host tesseract);
* vision-model OCR stays with the CALLER (agent.vision import would
  cycle here) following the tools/pdf_tool.py lazy-import pattern.

Bounded: at most MAX_PPTX_IMAGES_PER_DECK pictures per file and
MAX_PPTX_IMAGES_PER_SLIDE per slide; each OCR result capped to
MAX_PPTX_IMAGE_CHARS. Everything never raises. stdlib + pptx + PIL
only (services/ never touches tools/ or agent/).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_PPTX_IMAGES_PER_DECK: int = 6
MAX_PPTX_IMAGES_PER_SLIDE: int = 2
MAX_PPTX_IMAGE_CHARS: int = 2000

# MSO_SHAPE_TYPE.PICTURE. Compared by value (not enum import) so odd
# duck-typed shapes still work and a pptx upgrade cannot break matching.
_PICTURE_SHAPE_TYPE: int = 13

# Auto-generated picture names ("Picture 1", "image.png") carry no author
# meaning — emitting them as alt text would be pure noise. Real
# author-written names ("TSP tour diagram") are kept.
_AUTO_NAME_RE = re.compile(r"^(picture\s+\d+|image\s*\d*\.\w+)$", re.IGNORECASE)


def is_picture_shape(shape: Any) -> bool:
    """True for picture shapes (never raises)."""
    try:
        st = getattr(shape, "shape_type", None)
        if st is not None and int(getattr(st, "value", st)) == _PICTURE_SHAPE_TYPE:
            return True
        return hasattr(shape, "image")
    except Exception:
        return False


def picture_alt_text(shape: Any) -> str:
    """Author-written picture description, else shape name, else "" (never raises).

    python-pptx exposes only ``shape.name`` publicly; the real alt text
    (``p:cNvPr/@descr``) needs a guarded hop through ``_element``
    (lxml, already a python-pptx dependency). Any hop failure falls
    back to the name so a library upgrade degrades to names, never errors.
    """
    try:
        el = getattr(shape, "_element", None)
        # Pictures store props under p:nvPicPr, graphic frames under
        # p:nvXxPr (property names vary by element class); try each.
        cnv = None
        for _prop in ("nvPicPr", "_nvPicPr", "nvXxPr", "_nvXxPr"):
            try:
                nv = getattr(el, _prop, None) if el is not None else None
                cand = getattr(nv, "cNvPr", None) if nv is not None else None
                if cand is not None:
                    cnv = cand
                    break
            except Exception:
                logger.debug("picture prop hop failed", exc_info=True)
                continue
        get = getattr(cnv, "get", None) if cnv is not None else None
        if callable(get):
            descr = str(get("descr") or "").strip()
            # Builders (including python-pptx add_picture) prefill descr
            # with the file name ("image.png") — same noise class as
            # auto names, not author-written alt text.
            if descr and not _AUTO_NAME_RE.match(descr):
                return descr
    except Exception:
        logger.debug("picture descr hop failed; falling back to name", exc_info=True)
    try:
        name = str(getattr(shape, "name", "") or "").strip()
    except Exception:
        name = ""
    if name and not _AUTO_NAME_RE.match(name):
        return name
    return ""


def picture_blob(shape: Any) -> Optional[bytes]:
    """Raw image bytes for a picture shape, or None (never raises)."""
    try:
        img = getattr(shape, "image", None)
        blob = getattr(img, "blob", None) if img is not None else None
        if isinstance(blob, (bytes, bytearray)) and len(blob) > 0:
            return bytes(blob)
        return None
    except Exception:
        logger.debug("picture blob read failed", exc_info=True)
        return None


def _iter_picture_shapes(prs: Any) -> Iterator[Tuple[int, Any]]:
    """Yield (slide_num, shape) for every shape in slide order (never raises).

    Unbounded shape walk (groups recursed); callers apply picture-type
    filtering and caps. Blob bytes are never touched here, so counting
    passes stay cheap.
    """
    try:
        slides = list(getattr(prs, "slides", []) or [])
    except Exception:
        return

    def _walk(shapes: Any) -> Iterator[Any]:
        try:
            items = list(shapes or [])
        except Exception:
            return
        for shape in items:
            yield shape
            try:
                sub = getattr(shape, "shapes", None)
                has_sub = bool(sub) if sub is not None else False
            except Exception:
                has_sub = False
            if has_sub:
                try:
                    yield from _walk(sub)
                except Exception:
                    logger.debug("group walk failed", exc_info=True)
                    continue

    for num, slide in enumerate(slides, start=1):
        try:
            shapes = _walk(getattr(slide, "shapes", None))
        except Exception:
            logger.debug("slide shapes walk failed", exc_info=True)
            continue
        for shape in shapes:
            yield num, shape


def iter_deck_pictures(prs: Any) -> Iterator[Tuple[int, str, Optional[bytes]]]:
    """Yield (slide_num, alt_text, blob) in slide order, bounded (never raises).

    At most MAX_PPTX_IMAGES_PER_SLIDE pictures per slide and
    MAX_PPTX_IMAGES_PER_DECK per deck. Alt text may be "" (caller runs
    the OCR ladder); blob may be None (alt-text-only picture entry).
    """
    taken = 0
    per_slide: Dict[int, int] = {}
    try:
        for num, shape in _iter_picture_shapes(prs):
            if taken >= MAX_PPTX_IMAGES_PER_DECK:
                return
            if per_slide.get(num, 0) >= MAX_PPTX_IMAGES_PER_SLIDE:
                continue
            try:
                if not is_picture_shape(shape):
                    continue
            except Exception:
                logger.debug("picture shape check failed", exc_info=True)
                continue
            try:
                yield num, picture_alt_text(shape), picture_blob(shape)
            except Exception:
                logger.debug("deck picture yield failed", exc_info=True)
                continue
            taken += 1
            per_slide[num] = per_slide.get(num, 0) + 1
    except Exception:
        logger.debug("deck picture iteration failed", exc_info=True)
        return


def count_skipped_pictures(prs: Any) -> int:
    """Pictures dropped by the deck/slide caps (never raises).

    Same walk and cap order as iter_deck_pictures, without touching blob
    bytes — callers report the count so capped diagrams are announced,
    never silently missing. 0 when nothing was cut (or on any failure).
    """
    try:
        total = 0
        kept = 0
        per_slide: Dict[int, int] = {}
        for num, shape in _iter_picture_shapes(prs):
            try:
                if not is_picture_shape(shape):
                    continue
            except Exception:
                logger.debug("skipped-picture shape check failed", exc_info=True)
                continue
            total += 1
            if kept >= MAX_PPTX_IMAGES_PER_DECK:
                continue
            if per_slide.get(num, 0) >= MAX_PPTX_IMAGES_PER_SLIDE:
                continue
            kept += 1
            per_slide[num] = per_slide.get(num, 0) + 1
        return max(0, total - kept)
    except Exception:
        logger.debug("skipped picture count failed", exc_info=True)
        return 0


def ocr_picture_on_device(blob: Optional[bytes]) -> str:
    """On-device OCR text for picture bytes; "" when unavailable (never raises)."""
    try:
        if not blob:
            return ""
        from services.ocr import ocr_image_bytes as _ocr

        text = (_ocr(blob) or "").strip()
        return text[:MAX_PPTX_IMAGE_CHARS].strip()
    except Exception:
        logger.debug("picture on-device OCR failed", exc_info=True)
        return ""


def format_picture_line(index: int, alt: str, ocr_text: str = "",
                        engine: str = "") -> str:
    """One text line for a deck picture (pure function, never raises)."""
    try:
        if alt:
            return f"[image {int(index)}: {alt}]"
        if ocr_text:
            label = f" ({engine})" if engine else " (OCR)"
            return f"[image {int(index)}{label}:\n{ocr_text}]"
        return ""
    except Exception:
        return ""


def picture_lines_for_slide(
    pictures: List[Tuple[str, Optional[bytes]]],
    start_index: int,
    vision_ocr: Any = None,
) -> Tuple[List[str], int]:
    """Text lines for one slide's pictures + count consumed (never raises).

    Args:
        pictures: [(alt_text, blob)] in slide order (already per-slide capped
            by the caller via iter_deck_pictures or manually).
        start_index: 1-based image number for the first picture.
        vision_ocr: Optional callable(blob) -> str for the vision-model
            rung of the ladder (callers lazy-import agent.vision like
            tools/pdf_tool.py); None skips vision entirely.

    Ladder per picture: alt text (free) -> on-device OCR -> vision OCR.
    Pictures yielding nothing are skipped silently (decorative images
    must not pollute context with empty markers).
    """
    lines: List[str] = []
    used = 0
    try:
        for alt, blob in pictures or []:
            idx = int(start_index) + used
            used += 1
            if alt:
                lines.append(format_picture_line(idx, alt))
                continue
            ocr_text, engine = "", ""
            try:
                ocr_text = ocr_picture_on_device(blob)
                engine = "OCR" if ocr_text else ""
            except Exception:
                ocr_text, engine = "", ""
            if not ocr_text and callable(vision_ocr):
                try:
                    ocr_text = str(vision_ocr(blob) or "").strip()[:MAX_PPTX_IMAGE_CHARS].strip()
                    engine = "vision-OCR" if ocr_text else ""
                except Exception:
                    ocr_text, engine = "", ""
            line = format_picture_line(idx, "", ocr_text, engine)
            if line:
                lines.append(line)
    except Exception:
        logger.debug("picture lines build failed", exc_info=True)
    return lines, used
