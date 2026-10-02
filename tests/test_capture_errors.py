"""Tests for AssemblyAI auth/billing error classification (capture.py).

A mid-session `Error` frame (e.g. code 1008 "Insufficient funds") must be
treated as an auth/billing failure, not a transient drop, so the supervisor
surfaces it instead of hot-reconnecting.
"""

from src.capture import (
    AssemblyAIAuthError,
    AssemblyAICapture,
    CaptureConfig,
    _is_auth_or_billing_error,
)


def test_insufficient_funds_error_is_classified():
    assert _is_auth_or_billing_error(
        1008, "Unauthorized Connection: Insufficient funds"
    )


def test_http_auth_codes_are_classified():
    for code in (401, 402, 403, 1008):
        assert _is_auth_or_billing_error(code, "")


def test_string_codes_are_classified():
    assert _is_auth_or_billing_error("1008", "Insufficient funds")


def test_keyword_variants_are_classified():
    assert _is_auth_or_billing_error(None, "Invalid API key")
    assert _is_auth_or_billing_error(3001, "billing quota exceeded")


def test_transient_error_is_not_classified():
    assert not _is_auth_or_billing_error(3005, "Server error, please retry")


def test_is_auth_error_reflects_state():
    cap = AssemblyAICapture(CaptureConfig(api_key="test-key"))
    assert cap.is_auth_error() is False
    cap.auth_error = AssemblyAIAuthError(1008, "Insufficient funds")
    assert cap.is_auth_error() is True
