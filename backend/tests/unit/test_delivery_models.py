"""
Unit tests for app.delivery.models — boundary transport Pydantic models (TDD red phase).

Run: python -m pytest tests/unit/test_delivery_models.py -v
Expected before Task 5: FAIL (ImportError)
Expected after Task 5:  PASS
"""

import pytest
import pydantic


def test_tool_outcome_defaults():
    from app.delivery.models import ToolOutcome

    outcome = ToolOutcome(ok=True)
    assert outcome.retryable is False
    assert outcome.resource_ref is None
    assert outcome.error_message is None


def test_requests_validate_required_fields():
    from app.delivery.models import DriveUploadRequest, GmailSendRequest

    with pytest.raises(pydantic.ValidationError):
        DriveUploadRequest()

    with pytest.raises(pydantic.ValidationError):
        GmailSendRequest()

    drive_req = DriveUploadRequest(
        file_path="/tmp/report.md",
        file_name="report.md",
        mime_type="text/markdown",
    )
    assert drive_req.folder_id is None

    gmail_req = GmailSendRequest(
        to="user@example.com",
        subject="ContractSentinel report",
        body="Report body text.",
    )
    assert gmail_req.attachment_path is None
    assert gmail_req.attachment_name is None


def test_delivery_result_service_literal():
    from app.delivery.models import DeliveryResult

    drive_result = DeliveryResult(service="drive", ok=True)
    assert drive_result.service == "drive"

    gmail_result = DeliveryResult(service="gmail", ok=True)
    assert gmail_result.service == "gmail"
