"""UTC-first timestamps. Internal code stores UTC; display converts local."""

from datetime import datetime, timezone
from typing import Optional


def utcnow_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def format_local(iso_str: str, fmt: str = "%I:%M %p") -> str:
    """Format an ISO timestamp in local time; "" when missing/unparseable."""
    try:
        dt = datetime.fromisoformat(str(iso_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime(fmt)
    except Exception:
        return ""


def utcnow_stamp(fmt: str = "%Y%m%d_%H%M") -> str:
    """Compact UTC timestamp for filenames/exports."""
    return datetime.now(timezone.utc).strftime(fmt)


def parse_iso(value: object) -> Optional[datetime]:
    """Parse an ISO timestamp; None when missing/unparseable."""
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None
