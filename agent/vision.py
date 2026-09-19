"""Vision fast-path: image attachments answered with real image content.

Tries each vision-capable tier in cascade order; on total failure returns
None so the caller falls back to the normal text cascade (never claims
analysis that did not happen). Vision failures never cool tiers for text
use. Image trust rules (untrusted data) come from services.vision.
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

from agent.budget import BudgetExhausted, RequestBudget
from agent.cascade import _all_skipped_permanent, _usable_tiers
import agent  # package-attr routing: test doubles on agent._invoke_bounded stay effective
from agent.executor import TokenStream
from agent.prompts import _as_text, strip_internal_reasoning

logger = logging.getLogger(__name__)


def vision_ocr_bytes(blob: bytes, budget: Optional[RequestBudget] = None) -> str:
    """Transcribe image bytes via a vision-capable tier ("" when unusable).

    OCR fallback for scanned PDFs when no on-device engine exists: the
    page raster is sent to a vision tier with a verbatim-transcription
    prompt. The caller bounds the page count (MAX_OCR_PAGES); this helper
    makes at most one model call per invocation. Returns "" when no
    vision tier is configured or every attempt fails — never raises, so
    tools degrade to an honest STATUS=EMPTY instead of failing.
    """
    if budget is not None:
        try:
            budget.count_llm()
        except BudgetExhausted:
            return ""
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
        for name, getter in _usable_tiers(None, None):
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
    for ref in (image_upload_ids or [])[:3]:
        url, err = prepare_image_data_url(ref)
        if url:
            data_urls.append(url)
        else:
            logger.info("req=%s vision skipped upload %s: %s", request_id, ref, err)
    # Legacy staged paths (pre-ID attachments) resolve through the vault too.
    if not data_urls:
        for ref in (image_upload_ids or [])[:3]:
            resolved = resolve_local_image(ref)
            if resolved is None:
                continue
            url, err = prepare_image_data_url(ref)
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
            budget.count_llm()
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
