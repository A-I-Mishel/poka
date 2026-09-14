"""Username/password account endpoints (public; rate-limited per IP).

POST /api/auth/signup + /login issue opaque session tokens (shown
once, Bearer from then on through the normal auth chain, so every
existing endpoint — chats, memory, uploads, KB — isolates per
account with no further changes). GET /api/auth/me reports who the
current token belongs to; POST /api/auth/logout revokes it.
POST /api/auth/change-password rotates the credential (all sessions
die, a fresh token returns); GET /api/auth/sessions lists live
sessions; POST /api/auth/logout-all revokes them all.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from backend import schemas
from backend.deps import UserContext, current_user
from services import accounts as accounts_svc
from services.accounts import (
    AccountAuthFailed,
    AccountError,
    AccountExists,
    AccountFull,
    AccountLocked,
    AccountWeakPassword,
)
from services.obs import event as obs_event
from services.ratelimit import extract_client_ip, get_rate_limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _agent(request: Request) -> str:
    """Short client hint stored with new sessions (device recognition)."""
    try:
        return str(request.headers.get("user-agent", "") or "")[:120]
    except Exception:
        return ""


def _auth_gate(request: Request) -> None:
    """Per-IP brute-force friction for signup/login (429 when spent)."""
    from services.ratelimit import rate_limit_headers

    peer = request.client.host if request.client else ""
    ip = extract_client_ip(request.headers.get("x-forwarded-for", ""), peer)
    verdict = get_rate_limiter().check("auth:%s" % ip, "auth")
    if not verdict.allowed:
        obs_event("ratelimit.deny", action="auth")
        raise HTTPException(
            status_code=429,
            detail="Too many attempts, retry in %ds." % int(verdict.retry_after + 0.5),
            headers=rate_limit_headers(verdict, "auth"),
        )


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


@router.post("/signup", response_model=schemas.SessionResponse, status_code=201)
def signup(body: schemas.AccountRequest, request: Request):
    """Create an account and open its first session (username not taken)."""
    _auth_gate(request)
    try:
        token, info = accounts_svc.signup(body.username, body.password,
                                          agent=_agent(request))
    except AccountExists as e:
        raise HTTPException(status_code=409, detail=str(e))
    except AccountFull as e:
        raise HTTPException(status_code=403, detail=str(e))
    except AccountWeakPassword as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"token": token, "username": info["username"], "user_id": info["user_id"]}


@router.post("/login", response_model=schemas.SessionResponse)
def login(body: schemas.AccountRequest, request: Request):
    """Verify credentials and open a session (failures never say which half)."""
    _auth_gate(request)
    try:
        token, info = accounts_svc.login(body.username, body.password,
                                         agent=_agent(request))
    except AccountLocked as e:
        raise HTTPException(status_code=429, detail=str(e))
    except AccountAuthFailed as e:
        raise HTTPException(status_code=401, detail=str(e))
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"token": token, "username": info["username"], "user_id": info["user_id"]}


def _require_account(ctx: UserContext) -> None:
    """401 unless the caller holds a live account session."""
    if ctx.source != "account":
        raise HTTPException(status_code=401, detail="Login required.")


@router.post("/change-password", response_model=schemas.SessionResponse)
def change_password(body: schemas.ChangePasswordRequest,
                    ctx: UserContext = Depends(current_user)):
    """Rotate the password; every session dies, a fresh token returns.

    The caller must store the new token — the presenting one is revoked
    with the rest, so a stolen session cannot survive the change.
    """
    _require_account(ctx)
    try:
        token, info = accounts_svc.change_password(
            ctx.user_id, body.current_password, body.new_password)
    except AccountAuthFailed as e:
        raise HTTPException(status_code=401, detail=str(e))
    except AccountWeakPassword as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"token": token, "username": info["username"], "user_id": info["user_id"]}


@router.get("/sessions", response_model=schemas.SessionListResponse)
def sessions(ctx: UserContext = Depends(current_user),
             authorization: Optional[str] = Header(default=None)):
    """List this account's live sessions, newest first."""
    _require_account(ctx)
    return {"sessions": accounts_svc.list_sessions(ctx.user_id,
                                                   _bearer(authorization))}


@router.post("/logout-all")
def logout_all(ctx: UserContext = Depends(current_user)):
    """Revoke every session for this account (all devices). Always 200."""
    _require_account(ctx)
    return {"ok": True, "revoked": int(accounts_svc.logout_all(ctx.user_id))}


@router.post("/logout")
def logout(authorization: Optional[str] = Header(default=None)):
    """Revoke the presenting session token (idempotent, always 200)."""
    accounts_svc.logout(_bearer(authorization))
    return {"ok": True}


@router.get("/me", response_model=schemas.MeResponse)
def me(ctx: UserContext = Depends(current_user)):
    """Who the current token belongs to (username only for accounts)."""
    return {
        "username": accounts_svc.username_for_user(ctx.user_id),
        "user_id": ctx.user_id,
        "source": ctx.source,
    }
