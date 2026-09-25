"""Get a Google OAuth refresh token for Pluto's Calendar integration.

One-time interactive setup (opens your browser for Google consent):

    python scripts/get_google_refresh_token.py \
        --client-id YOUR_CLIENT_ID \
        --client-secret YOUR_CLIENT_SECRET

Then put the printed refresh token into .env (local) and Render
(pluto-api Environment Variables) as GOOGLE_REFRESH_TOKEN, alongside
GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.

The client ID/secret come from Google Cloud Console:
APIs & Services > Credentials > Create Credentials > OAuth client ID
(type: Desktop app), with the Google Calendar API enabled for the project.
"""

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Mint a Google refresh token for Pluto.")
    parser.add_argument("--client-id", default=os.getenv("GOOGLE_CLIENT_ID", ""))
    parser.add_argument("--client-secret", default=os.getenv("GOOGLE_CLIENT_SECRET", ""))
    args = parser.parse_args()

    if not args.client_id or not args.client_secret:
        print("Missing --client-id / --client-secret (or GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET).")
        return 2

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Missing dependency: pip install google-auth-oauthlib")
        return 2

    from services.google import ALL_SCOPES as SCOPES

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": args.client_id,
                "client_secret": args.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        SCOPES,
    )
    creds = flow.run_local_server(port=0)
    if not creds.refresh_token:
        print("No refresh token returned; remove the app's access at "
              "myaccount.google.com/permissions and retry.")
        return 1
    print("\nAdd this to .env and Render (never commit it):")
    print("GOOGLE_REFRESH_TOKEN=" + creds.refresh_token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
