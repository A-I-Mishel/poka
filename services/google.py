"""Shared Google OAuth scopes (single place, never scattered).

Both Gmail and Calendar use the same Desktop-app client; requesting
all scopes at once means one consent covers every integration.
"""

from typing import Any, List, Optional

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
]

ALL_SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES


def google_credentials(scopes: List[str]) -> Optional[Any]:
    """OAuth credentials from env refresh token, or None when unconfigured.

    Single builder for Gmail + Calendar so client-id/secret/refresh
    handling cannot drift. Never raises, never logs secrets.
    """
    try:
        from google.oauth2.credentials import Credentials

        from services.secrets import get_secret

        client_id = (get_secret("GOOGLE_CLIENT_ID", "") or "").strip()
        client_secret = (get_secret("GOOGLE_CLIENT_SECRET", "") or "").strip()
        refresh_token = (get_secret("GOOGLE_REFRESH_TOKEN", "") or "").strip()
        if not (client_id and client_secret and refresh_token):
            return None
        return Credentials(
            None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",  # noqa: S106 (OAuth endpoint, not a credential)
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
        )
    except Exception:
        return None


def build_google_service(api: str, version: str, scopes: List[str]) -> Optional[Any]:
    """Build a Google API client, or None when unconfigured (never raises)."""
    try:
        creds = google_credentials(scopes)
    except Exception:
        return None
    if creds is None:
        return None
    try:
        from googleapiclient.discovery import build

        return build(api, version, credentials=creds)
    except Exception:
        return None
