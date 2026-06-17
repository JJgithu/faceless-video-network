"""
scripts/get_youtube_token.py
────────────────────────────────────────────────────────────────────────────
ONE-TIME SETUP SCRIPT — Generates a YouTube OAuth 2.0 refresh token using
a manual copy-paste flow (no redirect URI needed — avoids browser errors).

Prerequisites:
  1. Go to https://console.cloud.google.com
  2. APIs & Services → Library → Enable "YouTube Data API v3"
  3. APIs & Services → Credentials → + Create Credentials → OAuth client ID
     → Application type: Desktop app → Create → Download JSON

Usage:
  python scripts/get_youtube_token.py --credentials scripts/client_secret.json
"""

import argparse
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main():
    parser = argparse.ArgumentParser(
        description="Get YouTube OAuth refresh token for GitHub Actions"
    )
    parser.add_argument(
        "--credentials",
        required=True,
        help="Path to your client_secret JSON file from Google Cloud Console",
    )
    args = parser.parse_args()

    cred_path = Path(args.credentials)
    if not cred_path.exists():
        print(f"❌ File not found: {cred_path}")
        return

    print("📺 YouTube OAuth Setup")
    print("─" * 55)
    print("This will open a browser tab. Log in with the Google")
    print("account that owns your YouTube channel, then approve.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), scopes=SCOPES)

    # run_local_server with a FIXED port — much more reliable than port=0
    # If the browser still shows an error, see the note below.
    try:
        creds = flow.run_local_server(
            port=8080,
            open_browser=True,
            authorization_prompt_message="Opening browser for YouTube authorization...",
            success_message="✅ Authorization complete! You may close this tab.",
        )
    except Exception:
        # Fallback: fully manual copy-paste flow (no browser redirect needed)
        print()
        print("⚠️  Browser flow failed. Using manual copy-paste flow instead.")
        print()
        flow2 = InstalledAppFlow.from_client_secrets_file(str(cred_path), scopes=SCOPES)
        creds = flow2.run_console()

    print("\n✅ Authentication successful!\n")
    print("Add these 3 values as GitHub Secrets:")
    print("─" * 55)

    with open(cred_path) as f:
        client_data = json.load(f)
    info = client_data.get("installed") or client_data.get("web", {})

    print(f"YOUTUBE_CLIENT_ID     = {info.get('client_id', '(see JSON file)')}")
    print(f"YOUTUBE_CLIENT_SECRET = {info.get('client_secret', '(see JSON file)')}")
    print(f"YOUTUBE_REFRESH_TOKEN = {creds.refresh_token}")
    print()
    print("⚠️  Keep these secret — never commit them to your repo!")


if __name__ == "__main__":
    main()
