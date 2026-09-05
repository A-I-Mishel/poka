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
    prepare_image_data_url,
    resolve_local_image,
    vision_supported_tier,
    vision_trust_preamble,
)

from agent.budget import BudgetExhausted, RequestBudget
from agent.cascade import _usable_tiers
import agent  # package-attr routing: test doubles on agent._invoke_bounded stay effective
from agent.prompts import _as_text

logger = logging.getLogger(__name__)


def _try_vision_answer(
    request_id: str,
    user_input: str,
    image_upload_ids: List[str],
    budget: RequestBudget,
    first: Optional[str],
    tiers: Optional[Sequence[Tuple[str, Callable[[], Optional[BaseLanguageModel]]]]],
) -> Optional[Dict[str, Any]]:
    """Attempt a vision-grounded answer on a vision-capable tier.

    Returns the result dict on success, None when no capable tier is
    configured or all vision attempts fail (caller falls back to the
    normal text cascade). Vision failures never cool tiers for text use.
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
    for name, getter in _usable_tiers(first, tiers):
        if not vision_supported_tier(name):
            continue
        try:
            llm_instance = getter()
        except Exception:
            continue
        if llm_instance is None:
            continue
        try:
            try:
                budget.count_llm()
            except BudgetExhausted:
                return None  # let the normal cascade produce the budget message
            response = agent._invoke_bounded(
                llm_instance, [HumanMessage(content=payload)], budget=None
            )
            text = _as_text(response.content).strip()
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
