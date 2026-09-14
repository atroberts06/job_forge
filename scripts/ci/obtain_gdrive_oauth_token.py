#!/usr/bin/env python3
"""One-time local helper to obtain a Google Drive OAuth refresh token (DEF-001).

Run on a trusted workstation (never in CI). Prints values to store as GitHub
Environment secrets. Does not write secrets to disk or commit them.

Usage:
  set GDRIVE_CLIENT_ID=...
  set GDRIVE_CLIENT_SECRET=...
  python scripts/ci/obtain_gdrive_oauth_token.py
"""

from __future__ import annotations

import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main() -> int:
    client_id = os.environ.get("GDRIVE_CLIENT_ID")
    client_secret = os.environ.get("GDRIVE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "ERROR: Set GDRIVE_CLIENT_ID and GDRIVE_CLIENT_SECRET before running.",
            file=sys.stderr,
        )
        return 1

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    credentials = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not credentials.refresh_token:
        print(
            "ERROR: No refresh token returned. Revoke prior app access in Google "
            "Account permissions, then re-run with prompt=consent.",
            file=sys.stderr,
        )
        return 1

    print("OAuth consent succeeded. Store these as GitHub production secrets:")
    print(f"GDRIVE_CLIENT_ID={client_id}")
    print(f"GDRIVE_CLIENT_SECRET={client_secret}")
    print(f"GDRIVE_REFRESH_TOKEN={credentials.refresh_token}")
    print()
    print("Do not commit these values. Keep GDRIVE_FOLDER_ID unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
