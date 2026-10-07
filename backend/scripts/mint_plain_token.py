"""
One-off: mint a PLAINTEXT central Google token for the Render Secret File.

Unlike scripts/oauth_bootstrap.py (which encrypts the token at rest for local dev),
this writes plaintext JSON — the form the Render deploy uses, so it works regardless of
whether the Render CONTRACTSENTINEL_ENCRYPTION_KEY matches this machine's key.

Run once, from the backend/ directory, AFTER placing the new Desktop-client JSON at
data/secrets/google_credentials.json:

    .venv/Scripts/python.exe scripts/mint_plain_token.py

A browser opens for consent; on approval the plaintext token is written to
data/secrets/google_token_plain.json. Paste its contents into the Render Secret File.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from app import config as _config  # noqa: E402
from app.delivery.mcp_servers.google_auth import SCOPES  # noqa: E402


def main() -> int:
    credentials_path = BACKEND_DIR / _config.GOOGLE_OAUTH_CREDENTIALS_PATH
    out_path = BACKEND_DIR / "data" / "secrets" / "google_token_plain.json"

    if not credentials_path.exists():
        print(f"ERROR: client secrets not found at {credentials_path}")
        print("Download the NEW Desktop-app OAuth client JSON and save it there.")
        return 1

    print(f"Client secrets: {credentials_path}")
    print("Requesting scopes:\n  " + "\n  ".join(SCOPES))
    print("\nOpening browser for consent...\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(creds.to_json(), encoding="utf-8")

    print(f"\nSuccess. PLAINTEXT token written to {out_path}")
    print("Open that file, copy ALL of it, and paste it into the Render Secret File "
          "'google_token.json'. Do NOT commit this file (data/secrets/ is gitignored).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
