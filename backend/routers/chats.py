"""Conversation history endpoints (mirrors sidebar chat semantics)."""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from backend import schemas
from backend.chatflow import archive_current
from backend.deps import UserContext, current_user
from services.limits import MAX_CHAT_TITLE_CHARS
from services.storage import StorageError

router = APIRouter(prefix="/api/chats", tags=["chats"])


def _load(ctx: UserContext):
    try:
        stored, _warnings = ctx.user_store.load_chats()
    except StorageError:
        stored = {"chats": [], "current": []}
    chats = stored.get("chats", []) if isinstance(stored, dict) else []
    current = stored.get("current", []) if isinstance(stored, dict) else []
    return (chats if isinstance(chats, list) else [],
            current if isinstance(current, list) else [])


@router.get("", response_model=schemas.ChatsResponse)
def list_chats(ctx: UserContext = Depends(current_user)):
    """Return archived chats plus the open conversation."""
    chats, current = _load(ctx)
    return {"chats": chats, "current": current}


@router.post("/new", response_model=schemas.ChatsResponse)
def new_chat(body: schemas.ArchiveRequest, ctx: UserContext = Depends(current_user)):
    """Archive the open conversation (if any) and start fresh."""
    chats, current = _load(ctx)
    if [m for m in current if isinstance(m, dict)]:
        try:
            record, current = archive_current(
                current, body.project_id, body.chat_id)
        except ValueError:
            current = []
        else:
            chats = [record] + list(chats)
            del chats[20:]
            ctx.user_store.save_chats(chats, current)
    return {"chats": chats, "current": current}


@router.post("/open", response_model=schemas.ChatsResponse)
def open_chat(body: schemas.OpenChatRequest, ctx: UserContext = Depends(current_user)):
    """Adopt an archived chat as the open conversation.

    Same semantics as the sidebar: the selected record leaves history,
    the previously open conversation is archived first.
    """
    chats, current = _load(ctx)
    selected = None
    rest: List[Dict[str, Any]] = []
    for chat in chats:
        if selected is None and isinstance(chat, dict) and str(chat.get("id", "")) == body.id:
            selected = chat
        else:
            rest.append(chat)
    if selected is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    if [m for m in current if isinstance(m, dict)]:
        try:
            record, _ = archive_current(
                current,
                selected.get("project_id") if isinstance(selected, dict) else None)
            rest = [record] + rest
        except ValueError:
            pass
    messages = selected.get("messages", []) if isinstance(selected, dict) else []
    ctx.user_store.save_chats(rest, messages if isinstance(messages, list) else [])
    return {"chats": rest, "current": messages}


@router.patch("/{chat_id}", response_model=schemas.ChatsResponse)
def rename_chat(chat_id: str, body: schemas.RenameRequest,
                ctx: UserContext = Depends(current_user)):
    """Rename an archived conversation."""
    chats, current = _load(ctx)
    found = False
    for chat in chats:
        if isinstance(chat, dict) and str(chat.get("id", "")) == chat_id:
            chat["title"] = body.title.strip()[:MAX_CHAT_TITLE_CHARS] or chat.get("title", "Untitled")
            found = True
    if not found:
        raise HTTPException(status_code=404, detail="Chat not found.")
    ctx.user_store.save_chats(chats, current)
    return {"chats": chats, "current": current}


@router.delete("/{chat_id}", response_model=schemas.ChatsResponse)
def delete_chat(chat_id: str, ctx: UserContext = Depends(current_user)):
    """Delete an archived conversation."""
    chats, current = _load(ctx)
    kept = [c for c in chats
            if not (isinstance(c, dict) and str(c.get("id", "")) == chat_id)]
    if len(kept) == len(chats):
        raise HTTPException(status_code=404, detail="Chat not found.")
    ctx.user_store.save_chats(kept, current)
    return {"chats": kept, "current": current}


@router.delete("", response_model=schemas.ChatsResponse)
def clear_current(ctx: UserContext = Depends(current_user)):
    """Clear the open conversation without archiving (fresh start)."""
    chats, _current = _load(ctx)
    ctx.user_store.save_chats(chats, [])
    return {"chats": chats, "current": []}


@router.post("/truncate", response_model=schemas.ChatsResponse)
def truncate_current(body: schemas.TruncateRequest,
                     ctx: UserContext = Depends(current_user)):
    """Cut the open conversation at an index (message Edit flow).

    Keeps messages[:index]; used to re-draft a user message and resend.
    """
    chats, current = _load(ctx)
    if not (0 <= int(body.index) <= len(current)):
        raise HTTPException(status_code=400, detail="Nothing to edit.")
    trimmed = current[:int(body.index)]
    ctx.user_store.save_chats(chats, trimmed)
    return {"chats": chats, "current": trimmed}
