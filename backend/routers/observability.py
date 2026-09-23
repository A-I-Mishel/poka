"""Observability endpoints: /api/metrics, /api/health/detailed, /debug/pprof"""

import platform
import secrets as _secrets
import shutil
import time
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from backend.deps import UserContext, current_user
from services.metrics import PRIVILEGED_METRIC_FAMILIES, REGISTRY
from services.secrets import get_secret
from services.structured_logging import get_logger
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

logger = get_logger("pluto.observability")
router = APIRouter(prefix="/api", tags=["observability"])


def _is_privileged_metrics_viewer(request: Request) -> bool:
    """True when the scraper may see identity-bearing series.

    Privileged = presenting PLUTO_METRICS_TOKEN (Bearer or
    X-Pluto-Metrics-Token, constant-time compare) or a stable
    authenticated identity (session/account/token/env). Ephemeral
    open-mode visitors are never privileged.
    """
    try:
        configured = (get_secret("PLUTO_METRICS_TOKEN", "") or "").strip()
    except Exception:
        configured = ""
    if configured:
        presented = ""
        try:
            auth = (request.headers.get("authorization") or "").strip()
            scheme, _, value = auth.partition(" ")
            if scheme.lower() == "bearer" and value.strip():
                presented = value.strip()
            else:
                presented = (request.headers.get("x-pluto-metrics-token") or "").strip()
        except Exception:
            presented = ""
        try:
            if presented and _secrets.compare_digest(presented, configured):
                return True
        except Exception:
            logger.debug("metrics token compare failed", exc_info=True)
    # Stable session/token/env identity (never ephemeral visitor ids).
    try:
        from backend.deps import session_token_from
        from services.auth import authenticate

        try:
            auth_header = request.headers.get("authorization")
        except Exception:
            auth_header = None
        try:
            token, _via = session_token_from(request, auth_header)
        except Exception:
            token = None
        try:
            result = authenticate(token)
        except Exception:
            return False
        return result.identity.source in ("env", "token", "account")
    except Exception:
        return False


def _strip_privileged_families(payload: bytes) -> bytes:
    """Remove identity-bearing families from a Prometheus exposition."""
    try:
        text = payload.decode("utf-8")
    except Exception:
        return payload
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip("# ").strip()
        # HELP/TYPE lines: "# HELP pluto_x ..." / "# TYPE pluto_x ..."
        token = ""
        if line.startswith("#"):
            parts = stripped.split()
            # parts[0] is HELP|TYPE, parts[1] is the metric name
            if len(parts) >= 2:
                token = parts[1]
        else:
            token = line.split("{", 1)[0].split(" ", 1)[0].strip()
        base = token
        # prometheus_client counters expose _total/_created samples;
        # privileged families here are gauges, but match generically.
        for suffix in ("_total", "_created", "_bucket", "_sum", "_count"):
            if base.endswith(suffix):
                candidate = base[: -len(suffix)]
                if candidate in PRIVILEGED_METRIC_FAMILIES:
                    base = candidate
                    break
        if base in PRIVILEGED_METRIC_FAMILIES:
            continue
        out.append(line)
    return "".join(out).encode("utf-8")


class DetailedHealthResponse(BaseModel):
    ok: bool
    version: str
    uptime_seconds: float
    python_version: str
    platform: str
    checks: dict


_start_time = time.time()


@router.get("/metrics")
def metrics(request: Request):
    """Prometheus metrics exposition endpoint (public, filtered).

    Stays unauthenticated for orchestrators/scrapers (see
    test_detailed_health_private_requires_auth), but unauthenticated
    (ephemeral) scrapes receive a filtered exposition with
    identity-bearing families (user_id/identity labels) removed.
    Authenticated scrapers (stable session/token/env identity or
    PLUTO_METRICS_TOKEN) receive the full registry. Per-identity
    series are additionally cardinality-capped at the source (see
    services.obs) so one-shot identities cannot grow process memory
    without bound.
    """
    payload = generate_latest(REGISTRY)
    if _is_privileged_metrics_viewer(request):
        return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
    return Response(content=_strip_privileged_families(payload), media_type=CONTENT_TYPE_LATEST)


@router.get("/health/detailed", response_model=DetailedHealthResponse)
def health_detailed(ctx: UserContext = Depends(current_user)):
    """Detailed health check with dependency status (authenticated).

    Gated because it discloses paths, versions and backend state.
    """
    checks = {}

    # Storage (shutil.disk_usage works on Windows and POSIX alike).
    # Probe the nearest existing ancestor: a fresh data dir may not
    # exist yet, and a health check must not create directories.
    try:
        from services.storage import data_root
        data_path = data_root()
        probe = data_path
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        usage = shutil.disk_usage(str(probe))
        checks["storage"] = {
            "ok": True,
            "data_dir": str(data_path),
            "free_bytes": usage.free,
            "free_percent": round(usage.free / usage.total * 100, 1) if usage.total else 0.0,
        }
    except Exception as e:
        checks["storage"] = {"ok": False, "error": str(e)}

    # Redis (if configured)
    try:
        from services.ratelimit_redis import get_redis_client
        redis = get_redis_client()
        if redis:
            redis.ping()
            checks["redis"] = {"ok": True}
        else:
            checks["redis"] = {"ok": True, "note": "in-memory limiter"}
    except Exception as e:
        checks["redis"] = {"ok": False, "error": str(e)}

    # FAISS index file census (layout owned by services.kb_index, which
    # stays parked WIP; search itself is out of scope for a health check).
    try:
        from services.storage import data_root
        users_root = data_root() / "users"
        indexed = 0
        if users_root.is_dir():
            for user_dir in users_root.iterdir():
                try:
                    if user_dir.is_dir() and (user_dir / "kb.faiss.index").is_file():
                        indexed += 1
                except OSError:
                    continue
        checks["faiss"] = {"ok": True, "indexed_users": indexed}
    except Exception as e:
        checks["faiss"] = {"ok": False, "error": str(e)}

    # LLM tiers (quick probe - non-blocking)
    try:
        from config import TIER_GETTERS
        configured = []
        for name, getter in TIER_GETTERS:
            try:
                if getter() is not None:
                    configured.append(name)
            except Exception:
                logger.debug("tier getter failed", tier=name, exc_info=True)
        checks["llm_tiers"] = {"ok": True, "configured": configured}
    except Exception as e:
        checks["llm_tiers"] = {"ok": False, "error": str(e)}

    all_ok = all(c.get("ok", False) for c in checks.values())
    return DetailedHealthResponse(
        ok=all_ok,
        version="0.1.0",
        uptime_seconds=round(time.time() - _start_time, 1),
        python_version=platform.python_version(),
        platform=platform.platform(),
        checks=checks,
    )


# ---- pprof endpoints (CPU, heap, goroutine-style) ----
# Note: Python doesn't have native pprof; we expose /debug/pprof/* endpoints
# compatible with py-spy / pyrasite / gperftools via profile conversion.

@router.get("/debug/pprof/profile")
def pprof_cpu_profile(seconds: int = 30, ctx: UserContext = Depends(current_user)):
    """CPU profile via py-spy (requires py-spy installed and root/capabilities)."""
    # In production, run py-spy as sidecar or use `py-spy record -o profile.pb.gz --pid <pid>`
    # This endpoint documents the capability; actual profiling done externally.
    return {
        "message": "Use 'py-spy record -o profile.pb.gz --pid <pid> --duration <seconds>' on the container",
        "example": "kubectl exec <pod> -- py-spy record -o /tmp/profile.pb.gz --pid 1 --duration 30",
    }


@router.get("/debug/pprof/heap")
def pprof_heap_profile(ctx: UserContext = Depends(current_user)):
    """Heap profile via an external profiler (tracemalloc intentionally not used).

    A per-request tracemalloc start/snapshot/stop would only capture
    microseconds of allocations (near-useless data) while disturbing
    global tracer state and burning CPU on every hit — so this endpoint
    documents the capability like the CPU one above; actual profiling
    is done externally (py-spy sidecar, memray).
    """
    return {
        "message": "Heap profiling is done externally; this endpoint takes no snapshots",
        "example": "py-spy dump --pid <pid> / memray run -o /tmp/out.bin uvicorn backend.main:app",
    }
