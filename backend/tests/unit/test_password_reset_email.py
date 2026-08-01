"""
Unit tests for the reset-email builder (feature 034).
"""

import app.config as _config


def test_build_reset_email_contains_url_and_brand():
    from app.delivery.password_reset_email import build_reset_email

    url = "http://localhost:3000/reset?token=RAWTOKEN123"
    subject, plain, html = build_reset_email(url)

    assert subject and isinstance(subject, str)
    assert url in plain
    assert url in html
    assert _config.REPORT_BRAND_NAME in html
    # HTML uses the URL as the CTA link target
    assert f'href="{url}"' in html
