"""
scripts/get_youtube_token.py
────────────────────────────────────────────────────────────────────────────
ONE-TIME SETUP SCRIPT — Run this locally on your Windows machine to generate
a YouTube OAuth 2.0 refresh token, then save it as a GitHub Secret.

Prerequisites:
  1. Create a Google Cloud project at https://console.cloud.google.com
  2. Enable the YouTube Data API v3
  3. Create OAuth 2.0 credentials (Desktop App type)
  4. Download the credentials JSON file

Usage:
  pip install google-auth-oauthlib
  python scripts/get_youtube_token.py --credentials path/to/client_secret.json

After running, copy the printed YOUTUBE_REFRESH_TOKEN to your GitHub repo:
  Settings → Secrets and variables → Actions → New repository secret
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
        help="Path to your OAuth 2.0 client_secret JSON file from Google Cloud Console",
    )
    args = parser.parse_args()

    cred_path = Path(args.credentials)
    if not cred_path.exists():
        print(f"❌ File not found: {cred_path}")
        return

    print("📺 YouTube OAuth Setup")
    print("─" * 50)
    print("A browser window will open. Log in to the Google account")
    print("that owns your YouTube channel and grant permissions.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), scopes=SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n✅ Authentication successful!\n")
    print("Add these values as GitHub Secrets:")
    print("─" * 50)

    # Load client info from file
    with open(cred_path) as f:
        client_data = json.load(f)
    info = client_data.get("installed") or client_data.get("web", {})

    print(f"YOUTUBE_CLIENT_ID     = {info.get('client_id', 'see credentials file')}")
    print(f"YOUTUBE_CLIENT_SECRET = {info.get('client_secret', 'see credentials file')}")
    print(f"YOUTUBE_REFRESH_TOKEN = {creds.refresh_token}")
    print()
    print("⚠️  Keep these secret — never commit them to your repo!")


if __name__ == "__main__":
    main()
