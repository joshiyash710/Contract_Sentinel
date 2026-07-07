"""
Google OAuth credential loading and service construction for MCP servers (D9/D10).

Never launches interactive consent — token must be pre-provisioned (spec §5.4).
"""

import os

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/gmail.send",
]


class CredentialsError(Exception):
    """Raised when OAuth credentials are absent, invalid, or cannot be refreshed."""


def load_credentials(credentials_path: str, token_path: str) -> Credentials:
    if not os.path.exists(token_path):
        raise CredentialsError("token not found; run one-time OAuth setup")

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                raise CredentialsError(f"token refresh failed: {exc}") from exc
        else:
            raise CredentialsError("credentials invalid and cannot be refreshed")

    return creds


def build_drive_service(creds: Credentials):
    return build("drive", "v3", credentials=creds)


def build_gmail_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds)
