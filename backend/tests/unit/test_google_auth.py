"""
Unit tests for app.delivery.mcp_servers.google_auth (TDD red phase).

All Google libs are patched — no network, no real token files.

Run: python -m pytest tests/unit/test_google_auth.py -v
Expected before Task 7: FAIL (ImportError)
Expected after Task 7:  PASS
"""

import pytest
from unittest.mock import MagicMock, patch


def test_missing_token_raises_credentials_error(tmp_path):
    """A non-existent token path raises CredentialsError — no interactive consent (D9)."""
    from app.delivery.mcp_servers.google_auth import load_credentials, CredentialsError

    non_existent = str(tmp_path / "no_token.json")
    with pytest.raises(CredentialsError, match="token not found"):
        load_credentials("creds.json", non_existent)


def test_expired_token_refreshed(tmp_path):
    """An expired credential with a refresh_token triggers creds.refresh(Request())."""
    token_file = tmp_path / "token.json"
    token_file.write_text("{}")

    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "refresh_tok"

    with (
        patch(
            "app.delivery.mcp_servers.google_auth.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        ),
        patch("app.delivery.mcp_servers.google_auth.Request") as MockRequest,
    ):
        from app.delivery.mcp_servers.google_auth import load_credentials

        result = load_credentials("creds.json", str(token_file))
        mock_creds.refresh.assert_called_once_with(MockRequest())
        assert result is mock_creds


def test_build_services():
    """build_drive_service / build_gmail_service call googleapiclient.discovery.build."""
    mock_creds = MagicMock()

    with patch("app.delivery.mcp_servers.google_auth.build") as mock_build:
        from app.delivery.mcp_servers.google_auth import (
            build_drive_service,
            build_gmail_service,
        )

        build_drive_service(mock_creds)
        mock_build.assert_called_with("drive", "v3", credentials=mock_creds)

        build_gmail_service(mock_creds)
        mock_build.assert_called_with("gmail", "v1", credentials=mock_creds)
