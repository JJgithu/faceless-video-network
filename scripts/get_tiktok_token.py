"""
scripts/get_tiktok_token.py
────────────────────────────────────────────────────────────────────────────
ONE-TIME SETUP SCRIPT — Guides you through the TikTok OAuth flow to obtain
a long-lived access token for the Content Posting API.

TikTok Developer Setup:
  1. Go to https://developers.tiktok.com
  2. Create an app and request access to "Content Posting API"
  3. Add redirect URI: http://localhost:8080/callback
  4. Note your Client Key and Client Secret

Usage:
  python scripts/get_tiktok_token.py --client-key YOUR_KEY --client-secret YOUR_SECRET

After running, add the printed values as GitHub Secrets.

NOTE: TikTok access tokens expire after 24 hours by default.
      The pipeline uses the refresh token to automatically renew them.
      For a long-running bot, you'll need to re-run this script periodically
      OR configure your TikTok app for the "refresh_token" grant type
      (requires additional app approval from TikTok).
"""

import argparse
import hashlib
import http.server
import os
import secrets
import threading
import urllib.parse
import webbrowser
from typing import Optional

import requests

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
SCOPES = "user.info.basic,video.publish,video.upload"


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP server to capture the OAuth callback."""
    auth_code: Optional[str] = None
    state: Optional[str] = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.auth_code = params.get("code", [None])[0]
        _CallbackHandler.state = params.get("state", [None])[0]

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<h1>Authorised! You can close this tab.</h1>")

    def log_message(self, *args):
        pass  # suppress server logs


def main():
    parser = argparse.ArgumentParser(description="Get TikTok OAuth access token")
    parser.add_argument("--client-key",    required=True)
    parser.add_argument("--client-secret", required=True)
    parser.add_argument(
        "--redirect-uri",
        default="http://localhost:8080/callback",
        help="The redirect URI registered in TikTok developer portal (use your ngrok URL)",
    )
    args = parser.parse_args()
    redirect_uri = args.redirect_uri
    print(f"Using redirect URI: {redirect_uri}")

    state = secrets.token_urlsafe(16)
    code_verifier = secrets.token_urlsafe(48)
    code_challenge = hashlib.sha256(code_verifier.encode()).hexdigest()

    params = {
        "client_key":            args.client_key,
        "scope":                 SCOPES,
        "response_type":         "code",
        "redirect_uri":          redirect_uri,
        "state":                 state,
        "code_challenge":        code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = TIKTOK_AUTH_URL + "?" + urllib.parse.urlencode(params)

    print("🎵 TikTok OAuth Setup")
    print("─" * 50)
    print("Opening your browser for TikTok login…")
    print(f"\nIf it doesn't open, visit:\n{auth_url}\n")

    # Start local callback server in background
    server = http.server.HTTPServer(("localhost", 8080), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    webbrowser.open(auth_url)

    # Wait for callback
    print("Waiting for TikTok callback…")
    while _CallbackHandler.auth_code is None:
        import time; time.sleep(0.5)
    server.shutdown()

    code = _CallbackHandler.auth_code
    print(f"\n✅ Got auth code: {code[:20]}…")

    # Exchange code for tokens
    resp = requests.post(
        TIKTOK_TOKEN_URL,
        data={
            "client_key":     args.client_key,
            "client_secret":  args.client_secret,
            "code":           code,
            "grant_type":     "authorization_code",
            "redirect_uri":   redirect_uri,
            "code_verifier":  code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json().get("data", resp.json())

    print("\n✅ Tokens obtained!\n")
    print("Add these as GitHub Secrets:")
    print("─" * 50)
    print(f"TIKTOK_CLIENT_KEY    = {args.client_key}")
    print(f"TIKTOK_CLIENT_SECRET = {args.client_secret}")
    print(f"TIKTOK_ACCESS_TOKEN  = {data.get('access_token', 'ERROR')}")
    print()
    print(f"Token expires in: {data.get('expires_in', 'unknown')} seconds")
    print(f"Refresh token:    {data.get('refresh_token', 'not provided')}")
    print()
    print("⚠️  TikTok access tokens expire after 24h.")
    print("   You may need to re-run this script periodically.")
    print("   Consider a TikTok session management service for production.")


if __name__ == "__main__":
    main()
