"""Chat export: organized PDF download of a conversation (A4).

POST /api/chats/export-pdf renders either an archived chat (chat_id,
ownership-checked like the other chats endpoints) or caller-supplied
messages (the open conversation) into a structured markdown transcript
and converts it with the dependency-free stdlib PDF builder
(tools.make_tool, A4). Direct download: nothing is persisted and no
generation quota is consumed — export is not creation.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from backend.deps import UserContext, current_user
from services.timeutil import utcnow_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chats", tags=["chats"])

# Total transcript cap mirrors the create_pdf input bound: oversized
# histories drop oldest turns (with a note) instead of failing.
EXPORT_MAX_MESSAGES: int = 500
EXPORT_MAX_CHARS: int = 200_000


class ExportPdfRequest(BaseModel):
    chat_id: Optional[str] = Field(default=None, max_length=64)
    title: Optional[str] = Field(default=None, max_length=120)
    # Bounded to EXPORT_MAX_MESSAGES (500): larger payloads are rejected
    # with 413 before markdown rendering to avoid RAM/CPU DoS.
    messages: Optional[List[Dict[str, Any]]] = Field(default=None, max_length=500)


def _safe_text(value: Any, limit: int = 20000) -> str:
    """Plain-text coercion for export fields (never raises)."""
    try:
        text = str(value if value is not None else "")
        return text[:limit]
    except Exception:
        return ""


def chat_export_markdown(title: str, messages: List[Dict[str, Any]],
                         exported_at: Optional[str] = None) -> str:
    """Render messages as an organized export transcript (never raises).

    Structure: title header + export line, then one section per turn —
    "## You · time" / "## Pluto · time · tier" — with attachments,
    content (critique scaffolds stripped), sources, and artifacts.
    Internal UI metadata (corrections, fallback banners, approval
    tokens) is deliberately excluded: it describes the app, not the
    conversation.
    """
    try:
        from agent.prompts import strip_internal_reasoning as _strip
    except Exception:
        def _strip(text: str) -> str:  # type: ignore[misc]
            return str(text or "")

    lines: List[str] = []
    try:
        clean_title = _safe_text(title, 120).strip() or "chat"
        turns = [m for m in (messages or []) if isinstance(m, dict)]
        if len(turns) > EXPORT_MAX_MESSAGES:
            turns = turns[-EXPORT_MAX_MESSAGES:]
        stamp = exported_at or utcnow_iso()
        lines = [f"# {clean_title}", "",
                 f"_Exported {stamp} · {len(turns)} messages_", ""]
        for m in turns:
            try:
                role = str(m.get("role", "") or "").lower()
                if role == "user":
                    head = "## You"
                else:
                    head = "## Pluto"
                when = _safe_text(m.get("time", ""), 64).strip()
                if when:
                    head += f" · {when}"
                if role != "user":
                    model = _safe_text(m.get("model", ""), 64).strip()
                    if model:
                        head += f" · {model}"
                lines.append(head)
                atts = m.get("attachments") or []
                names = [str(a.get("name", "") or "").strip()
                         for a in atts if isinstance(a, dict)]
                names = [n for n in names if n]
                if names:
                    lines.append("_Attachments: " + ", ".join(names[:10]) + "_")
                content = _safe_text(m.get("content", ""), 20000)
                try:
                    content = _strip(content)
                except Exception:
                    logger.debug("export strip failed", exc_info=True)
                lines.append(content or "(empty message)")
                sources = m.get("sources") or []
                shown = [(str(s.get("title", "") or "").strip(),
                          str(s.get("url", "") or "").strip())
                         for s in sources if isinstance(s, dict)]
                shown = [(t, u) for t, u in shown if t or u][:10]
                if shown:
                    lines.append("")
                    lines.append("Sources:")
                    for t, u in shown:
                        label = t or u
                        lines.append(f"- {label} ({u})" if u else f"- {label}")
                arts = m.get("artifacts") or []
                anames = [str(a.get("name", "") or "").strip()
                          for a in arts if isinstance(a, dict)]
                anames = [n for n in anames if n]
                if anames:
                    lines.append("_Files: " + ", ".join(anames[:10]) + "_")
                lines.append("")
            except Exception:
                logger.debug("export turn render failed; skipping turn", exc_info=True)
                continue
        text = "\n".join(lines).strip() + "\n"
        if len(text) > EXPORT_MAX_CHARS:
            # Drop oldest turns until under budget (keep header + note).
            body = "\n".join(lines[3:])
            while len(body) > EXPORT_MAX_CHARS - 500 and "\n## " in body:
                body = body.split("\n## ", 1)[1]
                body = "## " + body
            text = ("\n".join(lines[:3])
                    + "_Note: older turns omitted (export size limit)._\n\n" + body)
        return text
    except Exception:
        logger.debug("export markdown failed", exc_info=True)
        return f"# {_safe_text(title, 120) or 'chat'}\n\n(export failed)\n"


def _pdf_filename(title: str) -> str:
    """Sanitized download filename (mirrors the old .md exporter)."""
    try:
        base = re.sub(r"[^\w\- ]+", "", str(title or "")).strip() or "chat"
        return base[:80]
    except Exception:
        return "chat"


@router.post("/export-pdf")
def export_pdf(body: ExportPdfRequest, ctx: UserContext = Depends(current_user)):
    """Download a chat transcript as PDF (A4). Archived or inline."""
    from backend.routers.chats import _load

    title = (body.title or "").strip()
    messages: List[Dict[str, Any]] = []
    if body.chat_id:
        chats, _current = _load(ctx)
        selected = None
        for c in chats:
            if isinstance(c, dict) and str(c.get("id", "")) == body.chat_id:
                selected = c
                break
        if selected is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        raw = selected.get("messages", [])
        messages = [m for m in raw if isinstance(m, dict)] if isinstance(raw, list) else []
        title = title or str(selected.get("title", "") or "chat")
    elif body.messages is not None:
        if not isinstance(body.messages, list):
            raise HTTPException(status_code=400, detail="messages must be a list.")
        if len(body.messages) > EXPORT_MAX_MESSAGES:
            raise HTTPException(status_code=413, detail="Too many messages to export.")
        messages = [m for m in body.messages if isinstance(m, dict)]
        title = title or "chat"
    else:
        raise HTTPException(status_code=400, detail="chat_id or messages required.")
    if not messages:
        raise HTTPException(status_code=400, detail="Chat has no messages to export.")
    markdown = chat_export_markdown(title, messages)
    try:
        from tools.make_tool import _build_pdf, _parse_blocks
    except Exception:
        raise HTTPException(status_code=500, detail="PDF builder unavailable.")
    try:
        blocks = _parse_blocks(markdown)
        data = _build_pdf(title.strip()[:120] or "chat", blocks)
        from pypdf import PdfReader
        import io as _io

        if not PdfReader(_io.BytesIO(data)).pages:
            raise ValueError("no pages")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="PDF build failed.")
    name = _pdf_filename(title)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'},
    )
