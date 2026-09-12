"""Shared Google OAuth scopes (single place, never scattered).

Both Gmail and Calendar use the same Desktop-app client; requesting
all scopes at once means one consent covers every integration.
"""

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
]

ALL_SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES
