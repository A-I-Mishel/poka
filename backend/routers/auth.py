"""Username/password account endpoints (public; rate-limited per IP).

POST /api/auth/signup + /login issue opaque session tokens (shown
once, Bearer from then on through the normal auth chain, so every
existing endpoint — chats, memory, uploads, KB — isolates per
account with no further changes). GET /api/auth/me reports who the
current token belongs to; POST /api/auth/logout revokes it.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from backend import schemas
from backend.deps import UserContext, current_user
from services import accounts as accounts_svc
from services.accounts import AccountAuthFailed, AccountError, AccountExists, AccountFull
from services.obs import event as obs_event
from services.ratelimit import extract_client_ip, get_rate_limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
        token, info = accounts_svc.signup(body.username, body.password)
    except AccountExists as e:
        raise HTTPException(status_code=409, detail=str(e))
    except AccountFull as e:
        raise HTTPException(status_code=403, detail=str(e))
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"token": token, "username": info["username"], "user_id": info["user_id"]}


@router.post("/login", response_model=schemas.SessionResponse)
def login(body: schemas.AccountRequest, request: Request):
    """Verify credentials and open a session (failures never say which half)."""
    _auth_gate(request)
    try:
        token, info = accounts_svc.login(body.username, body.password)
    except AccountAuthFailed as e:
        raise HTTPException(status_code=401, detail=str(e))
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"token": token, "username": info["username"], "user_id": info["user_id"]}


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
