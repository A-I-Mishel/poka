"""Conversation history endpoints (mirrors sidebar chat semantics)."""

from fastapi import APIRouter, Depends, HTTPException

from backend import schemas
from backend.chatflow import archive_current
from backend.deps import UserContext, current_user
from services.limits import MAX_CHAT_TITLE_CHARS
from services.storage import MAX_STORED_CHATS, StorageError

router = APIRouter(prefix="/api/chats", tags=["chats"])


def _sort_key(chat):
    # ponytail: ISO updated_at sorts chronologically; missing (legacy) = oldest
    return chat.get("updated_at", "") if isinstance(chat, dict) else ""


def _load(ctx: UserContext):
    try:
        stored, _warnings = ctx.user_store.load_chats()
    except StorageError:
        stored = {"chats": [], "current": []}
    chats = stored.get("chats", []) if isinstance(stored, dict) else []
    current = stored.get("current", []) if isinstance(stored, dict) else []
    chats = chats if isinstance(chats, list) else []
    # ponytail: keep DESC order but skip sort when already sorted (common path saves N log N)
    if chats and not all(_sort_key(chats[i]) >= _sort_key(chats[i+1]) for i in range(len(chats)-1)):
        chats = sorted(chats, key=_sort_key, reverse=True)
    return (chats,
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
    warnings: list = []
    if [m for m in current if isinstance(m, dict)]:
        try:
            record, current = archive_current(
                current, body.project_id, body.chat_id)
        except ValueError:
            current = []
        else:
            # ponytail: keep recents stable — same id replaces, not duplicates
            deduped = [c for c in chats if not (isinstance(c, dict) and c.get("id") == record.get("id"))]
            # ponytail: prepend-then-sort — fresh updated_at stays top, ties keep prepend order
            chats = sorted([record] + deduped, key=_sort_key, reverse=True)
            if len(chats) > MAX_STORED_CHATS:
                dropped = len(chats) - MAX_STORED_CHATS
                del chats[MAX_STORED_CHATS:]
                warnings.append(
                    f"Chat history is full ({MAX_STORED_CHATS} saved chats): "
                    f"the oldest {dropped} archived chat(s) were removed.")
            ctx.user_store.save_chats(chats, current)
    return {"chats": chats, "current": current, "warnings": warnings}


@router.post("/open", response_model=schemas.ChatsResponse)
def open_chat(body: schemas.OpenChatRequest, ctx: UserContext = Depends(current_user)):
    """Adopt an archived chat as the open conversation.

    Recents are ordered by updated_at DESC (newest on top). Browsing
    does not reorder: the selected chat becomes current, order is
    preserved. Only an unsaved current (diverged from every archived
    chat) is archived with a fresh updated_at so recently edited
    chats surface on top.
    """
    chats, current = _load(ctx)
    selected = None
    for c in chats:
        if isinstance(c, dict) and str(c.get("id", "")) == body.id:
            selected = c
            break
    if selected is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    # ponytail: keep recents stable on browse; only archive current if it
    # has diverged from every archived chat (unsaved edit/new chat).
    if [m for m in current if isinstance(m, dict)]:
        already_saved = any(
            isinstance(c, dict) and c.get("messages") == current for c in chats
        )
        if not already_saved:
            # reuse origin id when current is an edited version of an existing chat
            origin_id = None
            best_len = -1
            for c in chats:
                msgs = c.get("messages") if isinstance(c, dict) else None
                if isinstance(msgs, list) and len(msgs) <= len(current) and current[:len(msgs)] == msgs:
                    if len(msgs) > best_len:
                        best_len = len(msgs)
                        origin_id = c.get("id") if isinstance(c, dict) else None
            try:
                record, _ = archive_current(
                    current,
                    selected.get("project_id") if isinstance(selected, dict) else None,
                    origin_id)
                # same id replaces and moves to top; new id prepends
                if not any(isinstance(c, dict) and c.get("id") == record.get("id") for c in chats):
                    chats = [record] + chats
                else:
                    chats = [record] + [c for c in chats if c.get("id") != record.get("id")]
                chats = sorted(chats, key=_sort_key, reverse=True)
                if len(chats) > MAX_STORED_CHATS:
                    del chats[MAX_STORED_CHATS:]
            except ValueError:
                pass
    messages = selected.get("messages", []) if isinstance(selected, dict) else []
    # ponytail: do not pop selected from history — recents stay stable, newer on top
    ctx.user_store.save_chats(chats, messages if isinstance(messages, list) else [])
    return {"chats": chats, "current": messages}


@router.get("/{chat_id}/messages")
def chat_messages(chat_id: str, ctx: UserContext = Depends(current_user)):
    """Read one archived conversation's messages without opening it.

    Strictly read-only: stored state is untouched, so exporting any chat
    from the sidebar never disturbs the open conversation.
    """
    chats, _current = _load(ctx)
    for chat in chats:
        if isinstance(chat, dict) and str(chat.get("id", "")) == chat_id:
            messages = chat.get("messages", [])
            return {
                "id": chat_id,
                "title": chat.get("title", "Untitled"),
                "messages": messages if isinstance(messages, list) else [],
            }
    raise HTTPException(status_code=404, detail="Chat not found.")


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
