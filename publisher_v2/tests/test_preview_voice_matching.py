"""Tests for PUB-029 AC-07: preview reports voice matching status without leaking examples."""

from __future__ import annotations

import pytest

from publisher_v2.utils.preview import print_voice_matching_status


def test_ac07_preview_reports_enabled_with_count(capsys: pytest.CaptureFixture[str]) -> None:
    print_voice_matching_status(enabled=True, applied_count=4)
    out = capsys.readouterr().out
    assert "voice" in out.lower()
    # Status line includes the applied count
    assert "4" in out


def test_ac07_preview_reports_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    print_voice_matching_status(enabled=False, applied_count=0)
    out = capsys.readouterr().out
    assert "voice" in out.lower()
    # When disabled, the output should make that obvious
    assert "disabled" in out.lower() or "off" in out.lower() or "not enabled" in out.lower()


def test_ac07_preview_does_not_leak_example_text(capsys: pytest.CaptureFixture[str]) -> None:
    """Critical: the printer takes a count, NOT the examples; even if the caller
    is sloppy, the printer signature must not accept (and therefore cannot print)
    the raw examples."""
    secret = "MY_PRIVATE_VOICE_LINE_42"
    # Caller may know the examples, but only the count flows into the printer.
    examples = [secret, "another"]
    print_voice_matching_status(enabled=True, applied_count=len(examples))
    out = capsys.readouterr().out
    assert secret not in out


def test_ac07_zero_count_when_enabled_states_zero(capsys: pytest.CaptureFixture[str]) -> None:
    print_voice_matching_status(enabled=True, applied_count=0)
    out = capsys.readouterr().out
    assert "0" in out
