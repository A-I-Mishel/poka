"""Username/password account endpoints (public; rate-limited per IP).

POST /api/auth/signup + /login open a session and set it as an
HttpOnly `pluto_session` cookie (browsers) while ALSO returning the
raw token once in JSON (tests, non-browser clients, Bearer fallback
through the normal auth chain). GET /api/auth/me reports who the
current session belongs to; POST /api/auth/logout revokes it.
POST /api/auth/change-password rotates the credential (all sessions
die, a fresh cookie/token returns); GET /api/auth/sessions lists live
sessions; POST /api/auth/logout-all revokes them all.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from backend import schemas
from backend.deps import (
    SESSION_COOKIE,
    UserContext,
    current_user,
    session_token_from,
)
from services import accounts as accounts_svc
from services.accounts import (
    AccountAuthFailed,
    AccountError,
    AccountExists,
    AccountFull,
    AccountLocked,
    AccountUnavailable,
    AccountWeakPassword,
)
from services.obs import event as obs_event
from services.ratelimit import extract_client_ip, get_rate_limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Browsers keep the session in an HttpOnly cookie so injected JS
# cannot exfiltrate it via localStorage. 30d to match the server TTL.
_SESSION_MAX_AGE = 30 * 86400


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    """Set the HttpOnly session cookie (Secure on HTTPS only).

    Secure cookies are rejected over plain http (local dev, TestClient),
    so enable Secure only when the request itself arrived via https
    (prod/Vercel/Render). HttpOnly + SameSite=Lax hold in all modes.
    """
    try:
        scheme = (request.url.scheme or "").lower()
    except Exception:
        scheme = ""
    secure = scheme == "https"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


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
    if not ip or ip == "unknown":
        # Don't collapse all unknown-IP clients into one "auth:unknown"
        # bucket (DoS). Use peer-or-random so failures don't block others.
        import secrets as _secrets

        ip = (peer or "").strip() or ("anon-" + _secrets.token_hex(4))
    verdict = get_rate_limiter().check("auth:%s" % ip[:45], "auth")
    if not verdict.allowed:
        obs_event("ratelimit.deny", action="auth")
        raise HTTPException(
            status_code=429,
            detail="Too many attempts, retry in %ds." % int(verdict.retry_after + 0.5),
            headers=rate_limit_headers(verdict, "auth"),
        )


@router.post("/signup", response_model=schemas.SessionResponse, status_code=201)
def signup(body: schemas.AccountRequest, request: Request, response: Response):
    """Create an account and open its first session (username not taken)."""
    _auth_gate(request)
    try:
        token, info = accounts_svc.signup(body.username, body.password,
                                          agent=_agent(request))
    except AccountUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AccountExists as e:
        raise HTTPException(status_code=409, detail=str(e))
    except AccountFull as e:
        raise HTTPException(status_code=403, detail=str(e))
    except AccountWeakPassword as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _set_session_cookie(response, request, token)
    return {"token": token, "username": info["username"], "user_id": info["user_id"]}


@router.post("/login", response_model=schemas.SessionResponse)
def login(body: schemas.AccountRequest, request: Request, response: Response):
    """Verify credentials and open a session (failures never say which half)."""
    _auth_gate(request)
    try:
        token, info = accounts_svc.login(body.username, body.password,
                                         agent=_agent(request))
    except AccountUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AccountLocked as e:
        raise HTTPException(status_code=429, detail=str(e))
    except AccountAuthFailed as e:
        raise HTTPException(status_code=401, detail=str(e))
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _set_session_cookie(response, request, token)
    return {"token": token, "username": info["username"], "user_id": info["user_id"]}


def _require_account(ctx: UserContext) -> None:
    """401 unless the caller holds a live account session."""
    if ctx.source != "account":
        raise HTTPException(status_code=401, detail="Login required.")


@router.post("/change-password", response_model=schemas.SessionResponse)
def change_password(body: schemas.ChangePasswordRequest,
                    request: Request,
                    response: Response,
                    ctx: UserContext = Depends(current_user)):
    """Rotate the password; every session dies, a fresh cookie/token returns.

    The caller must use the new cookie/token — the presenting session is
    revoked with the rest, so a stolen session cannot survive the change.
    """
    _require_account(ctx)
    try:
        token, info = accounts_svc.change_password(
            ctx.user_id, body.current_password, body.new_password,
            agent=_agent(request))
    except AccountUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AccountAuthFailed as e:
        raise HTTPException(status_code=401, detail=str(e))
    except AccountWeakPassword as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _set_session_cookie(response, request, token)
    return {"token": token, "username": info["username"], "user_id": info["user_id"]}


@router.get("/sessions", response_model=schemas.SessionListResponse)
def sessions(request: Request,
             ctx: UserContext = Depends(current_user),
             authorization: Optional[str] = Header(default=None)):
    """List this account's live sessions, newest first."""
    _require_account(ctx)
    presented, _via = session_token_from(request, authorization)
    return {"sessions": accounts_svc.list_sessions(ctx.user_id, presented)}


@router.post("/logout-all")
def logout_all(response: Response, ctx: UserContext = Depends(current_user)):
    """Revoke every session for this account (all devices). Always 200."""
    _require_account(ctx)
    _clear_session_cookie(response)
    return {"ok": True, "revoked": int(accounts_svc.logout_all(ctx.user_id))}


@router.post("/logout")
def logout(request: Request, response: Response,
           authorization: Optional[str] = Header(default=None)):
    """Revoke the presenting session token (idempotent, always 200)."""
    presented, _via = session_token_from(request, authorization)
    accounts_svc.logout(presented)
    _clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=schemas.MeResponse)
def me(ctx: UserContext = Depends(current_user)):
    """Who the current token belongs to (username only for accounts)."""
    return {
        "username": accounts_svc.username_for_user(ctx.user_id),
        "user_id": ctx.user_id,
        "source": ctx.source,
    }
