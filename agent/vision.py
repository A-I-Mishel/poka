"""Vision fast-path: live cascade answering on vision-capable tiers.

Single job: ask a vision tier about image content and return the answer
(or None so the caller falls back to the text cascade — never claims
analysis that did not happen). Image DATA prep lives in
services/vision.py; cached image-to-text conversion lives in
services/image_bridge.py. Vision failures never cool tiers for text use.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from langchain_core.language_models.base import BaseLanguageModel
from langchain_core.messages import HumanMessage

from services.vision import (
    build_vision_messages,
    encode_image_bytes,
    prepare_image_data_url,
    resolve_local_image,
    vision_supported_tier,
    vision_trust_preamble,
)

from agent.budget import RequestBudget
from agent.cascade import _all_skipped_permanent, _usable_tiers
import agent  # package-attr routing: test doubles on agent._invoke_bounded stay effective
from agent.executor import TokenStream
from agent.prompts import _as_text, strip_internal_reasoning


def _preferred_vision_first() -> Optional[str]:
    """Pinned tier for vision-OCR preference, or None (never raises).

    Honors the request's picker selection when it names a vision-capable
    tier (e.g. Ollama VL 3B): document picture transcription then starts
    there instead of at the cascade head. Anything else (unset, unknown,
    text-only) yields None and cascade order applies unchanged.
    """
    try:
        from services.context import get_preferred_vision_tier

        first = get_preferred_vision_tier()
    except Exception:
        return None
    try:
        if first and vision_supported_tier(str(first)):
            return str(first)
    except Exception:
        return None
    return None

logger = logging.getLogger(__name__)


def vision_ocr_bytes(blob: bytes, budget: Optional[RequestBudget] = None) -> str:
    """Transcribe image bytes via a vision-capable tier ("" when unusable).

    OCR fallback for scanned PDFs when no on-device engine exists: the
    page raster is sent to a vision tier with a verbatim-transcription
    prompt. The caller bounds the page count (MAX_OCR_PAGES); this helper
    makes at most one model call per invocation. Returns "" when no
    vision tier is configured or every attempt fails — never raises, so
    tools degrade to an honest STATUS=EMPTY instead of failing.
    NOTE: budgeting is delegated to _invoke_bounded (don't pre-charge here
    or callers double-pay).
    """
    try:
        url, _err = encode_image_bytes(blob)
        if not url:
            return ""
        prompt = (
            vision_trust_preamble()
            + "\n\nTranscribe ALL visible text in this image verbatim. "
            "Return only the transcription, no commentary."
        )
        payload = build_vision_messages(prompt, [url])
        first = _preferred_vision_first()
        for name, getter in _usable_tiers(first, None):
            if not vision_supported_tier(name):
                continue
            try:
                llm_instance = getter()
            except Exception:
                logger.debug("tier=%s vision getter failed; trying next", name, exc_info=True)
                continue
            if llm_instance is None:
                continue
            try:
                response = agent._invoke_bounded(
                    llm_instance, [HumanMessage(content=payload)], budget=budget)
                text = strip_internal_reasoning(_as_text(response.content).strip())
                if text:
                    logger.info("tier=%s vision-ocr ok (%d chars)", name, len(text))
                    return text
            except Exception as e:
                logger.info("tier=%s vision-ocr failed: %s", name, e)
                continue
    except Exception:
        return ""
    return ""


def vision_ocr_many(blobs: Sequence[bytes], budget: Optional[RequestBudget] = None) -> List[str]:
    """Transcribe several image blobs in ONE vision-tier cascade call.

    Batch counterpart of vision_ocr_bytes for slide-grouped pictures: one
    model call carries every image instead of one cascade per picture.
    Returns per-blob texts aligned with the input ("" for blobs that
    fail encoding or come back empty — callers fall back to per-picture
    vision_ocr_bytes for those). Same conventions: tier iteration in
    cascade order, no cooling for text use, never raises (all-"" on
    failure), budgeting delegated to _invoke_bounded.
    """
    try:
        items = list(blobs or [])
        if not items:
            return []
        urls: List[Optional[str]] = []
        for blob in items:
            try:
                url, _err = encode_image_bytes(blob)
                urls.append(url)
            except Exception:
                urls.append(None)
        live = [i for i, url in enumerate(urls) if url]
        if not live:
            return [""] * len(items)
        prompt = (
            vision_trust_preamble()
            + f"\n\nYou are given {len(live)} images. For EACH image i "
            "(1-based, in order), output a section starting with exactly "
            "'IMAGE i' on its own line, then transcribe ALL visible text "
            "in that image verbatim below it. Return only the sections, "
            "no commentary."
        )
        parts: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for i in live:
            parts.append({"type": "image_url", "image_url": {"url": urls[i]}})
        payload = parts  # type: ignore[assignment]
        first = _preferred_vision_first()
        for name, getter in _usable_tiers(first, None):
            if not vision_supported_tier(name):
                continue
            try:
                llm_instance = getter()
            except Exception:
                logger.debug("tier=%s batch vision getter failed; trying next",
                             name, exc_info=True)
                continue
            if llm_instance is None:
                continue
            try:
                response = agent._invoke_bounded(
                    llm_instance, [HumanMessage(content=payload)], budget=budget)
                text = strip_internal_reasoning(_as_text(response.content).strip())
                if not text:
                    continue
                import re as _re

                sections = _re.split(r"(?im)^image\s*(\d+)\s*$", text)
                blocks: Dict[int, str] = {}
                try:
                    for j in range(1, len(sections) - 1, 2):
                        blocks[int(sections[j])] = sections[j + 1]
                except (TypeError, ValueError):
                    logger.debug("tier=%s batch section split failed", name,
                                 exc_info=True)
                out = [""] * len(items)
                for k, i in enumerate(live):
                    out[i] = str(blocks.get(k + 1, "") or "").strip()
                logger.info("tier=%s batch vision-ocr ok (%d/%d images)",
                            name, sum(1 for t in out if t), len(items))
                return out
            except Exception as e:
                logger.info("tier=%s batch vision failed: %s", name, e)
                continue
    except Exception:
        return [""] * len(list(blobs or []))
    return [""] * len(list(blobs or []))


def _try_vision_answer(
    request_id: str,
    user_input: str,
    image_upload_ids: List[str],
    budget: RequestBudget,
    first: Optional[str],
    tiers: Optional[Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]],
    on_token: Optional[Callable[[str], None]] = None,
    on_reset: Optional[Callable[[], None]] = None,
) -> Optional[Dict[str, Any]]:
    """Attempt a vision-grounded answer on a vision-capable tier.

    Returns the result dict on success, None when no capable tier is
    configured or all vision attempts fail (caller falls back to the
    normal text cascade). Vision failures never cool tiers for text use.
    on_token streams the single vision answer live; on_reset fires when
    a retry on another tier supersedes a partial stream. A TokenStream
    passed as on_token is shared (never re-wrapped).
    """
    data_urls: List[str] = []
    total_images = len(image_upload_ids or [])
    for ref in (image_upload_ids or [])[:3]:
        url, err = prepare_image_data_url(ref)
        if url:
            data_urls.append(url)
        else:
            logger.info("req=%s vision skipped upload %s: %s", request_id, ref, err)
    if total_images > 3:
        logger.info("req=%s vision capped at 3 of %d images", request_id, total_images)
    # Legacy staged paths (pre-ID attachments) resolve through the vault too.
    if not data_urls:
        for ref in (image_upload_ids or [])[:3]:
            resolved = resolve_local_image(ref)
            if resolved is None:
                continue
            url, err = prepare_image_data_url(resolved)
            if url:
                data_urls.append(url)
    if not data_urls:
        return None
    prompt = vision_trust_preamble() + "\n\nUser request:\n" + user_input
    payload = build_vision_messages(prompt, data_urls)
    tokens = on_token if isinstance(on_token, TokenStream) else TokenStream(on_token, on_reset)
    live = tokens if tokens.streaming else None
    # Fail fast if all vision tiers are quota-cooled (same as text cascade).
    if tiers is not None and _all_skipped_permanent(list(_usable_tiers(first, tiers))):
        return None
    for name, getter in _usable_tiers(first, tiers):
        if not vision_supported_tier(name):
            continue
        try:
            llm_instance = getter()
        except Exception:
            logger.debug("req=%s tier=%s vision getter failed; trying next", request_id, name, exc_info=True)
            continue
        if llm_instance is None:
            continue
        try:
            if live is not None:
                live.reset_for_new_call()
            response = agent._invoke_bounded(
                llm_instance, [HumanMessage(content=payload)], budget=budget,
                on_token=live,
            )
            text = strip_internal_reasoning(_as_text(response.content).strip())
            if not text:
                continue
            logger.info("req=%s tier=%s vision ok", request_id, name)
            if total_images > 3:
                text = (text.rstrip() + f"\n\n[Note: answered from the first 3 of "
                        f"{total_images} images; mention the others to continue.]")
            return {
                "output": text,
                "active_tier": name,
                "task_type": "vision",
                "request_id": request_id,
            }
        except Exception as e:
            logger.info("req=%s tier=%s vision failed: %s", request_id, name, e)
            continue
    return None
