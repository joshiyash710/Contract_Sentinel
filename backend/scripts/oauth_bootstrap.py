"""
One-time OAuth bootstrap: mint google_token.json for the delivery layer.

The runtime (app/delivery/mcp_servers/google_auth.py) never launches interactive
consent by design (spec §5.4) -- it only loads and refreshes a pre-provisioned
token. This script performs that one-time consent flow and writes the token to
the exact path the app expects.

Prerequisites (Google Cloud Console, project feedback-487517):
  1. Enable the Google Drive API and Gmail API.
  2. On the OAuth consent screen, add the drive.file + gmail.send scopes and add
     your account as a Test user (if the app is in "Testing" publishing status).

Run once, from the backend/ directory:

    .venv/Scripts/python.exe scripts/oauth_bootstrap.py

A browser window opens for consent; on approval google_token.json is written.
Re-run with --force to overwrite an existing token.
"""

import sys
from pathlib import Path

# Make the `app` package importable when run as `scripts/oauth_bootstrap.py`
# from backend/ (this file lives in backend/scripts/).
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from app import config as _config  # noqa: E402
from app.delivery.mcp_servers.google_auth import SCOPES  # noqa: E402


def main() -> int:
    force = "--force" in sys.argv[1:]

    # Config paths are backend/-relative; resolve against BACKEND_DIR so the
    # script works regardless of the current working directory.
    credentials_path = BACKEND_DIR / _config.GOOGLE_OAUTH_CREDENTIALS_PATH
    token_path = BACKEND_DIR / _config.GOOGLE_OAUTH_TOKEN_PATH

    if not credentials_path.exists():
        print(f"ERROR: client secrets not found at {credentials_path}")
        print("Download the Desktop-app OAuth client JSON and place it there.")
        return 1

    if token_path.exists() and not force:
        print(f"Token already exists at {token_path}")
        print("Delivery is already provisioned. Re-run with --force to overwrite.")
        return 0

    print(f"Client secrets: {credentials_path}")
    print(f"Requesting scopes:\n  " + "\n  ".join(SCOPES))
    print("\nOpening browser for consent...\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")

    print(f"\nSuccess. Token written to {token_path}")
    print("The delivery layer can now authenticate (refresh happens automatically).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
