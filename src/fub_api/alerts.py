"""Alerts for the refresh pipeline and high-value lead events.

Channels are config-driven via .env (callers should load_dotenv first):
  ALERT_WEBHOOK_URL   Slack- or Discord-style incoming webhook. If set, POSTs the alert.
  ALERT_MACOS         "1"/"true"/"yes" forces a macOS banner; defaults on under macOS.
  TWILIO_ACCOUNT_SID  +
  TWILIO_AUTH_TOKEN   +
  TWILIO_FROM         Twilio sender number (E.164, e.g. +14105551234) +
  ALERT_SMS_TO        comma-separated recipient numbers -> SMS via Twilio.
                      NOTE: a TRIAL Twilio account can only text numbers verified
                      in the Twilio console, and prefixes every message with
                      "Sent from your Twilio trial account".

Best-effort by design: a failing alert channel must never mask the original
error, so each channel swallows its own exceptions and logs to stderr.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys


def _macos_enabled() -> bool:
    raw = os.getenv("ALERT_MACOS")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes"}
    return platform.system() == "Darwin"


def _notify_macos(subject: str, body: str) -> None:
    first_line = body.splitlines()[0] if body else ""
    text = first_line.replace('"', "'")[:240]
    subj = subject.replace('"', "'")[:120]
    subprocess.run(
        ["osascript", "-e", f'display notification "{text}" with title "{subj}"'],
        check=False, capture_output=True, timeout=10,
    )


def _notify_webhook(url: str, subject: str, body: str) -> None:
    import httpx
    text = f"*{subject}*\n```\n{body[:1500]}\n```"
    # Slack reads "text", Discord reads "content"; send both so either accepts it.
    httpx.post(url, json={"text": text, "content": text}, timeout=10).raise_for_status()


def _notify_sms(subject: str, body: str) -> None:
    """SMS via the Twilio REST API (plain httpx — no twilio SDK dependency)."""
    import httpx
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    sender = os.getenv("TWILIO_FROM", "").strip()
    recipients = [r.strip() for r in os.getenv("ALERT_SMS_TO", "").split(",") if r.strip()]
    if not (sid and token and sender and recipients):
        return
    first_line = body.splitlines()[0] if body else ""
    text = f"{subject}\n{first_line}"[:320]  # 2 SMS segments max
    for to in recipients:
        httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, token),
            data={"From": sender, "To": to, "Body": text},
            timeout=15,
        ).raise_for_status()


def send_alert(subject: str, body: str = "") -> None:
    """Dispatch a failure alert to every configured channel. Never raises."""
    print(f"\n[alert] {subject}\n{body}", file=sys.stderr)

    if _macos_enabled():
        try:
            _notify_macos(subject, body)
        except Exception as e:  # noqa: BLE001
            print(f"[alert] macOS notification failed: {e}", file=sys.stderr)

    url = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    if url:
        try:
            _notify_webhook(url, subject, body)
        except Exception as e:  # noqa: BLE001
            print(f"[alert] webhook POST failed: {e}", file=sys.stderr)

    try:
        _notify_sms(subject, body)
    except Exception as e:  # noqa: BLE001
        print(f"[alert] Twilio SMS failed: {e}", file=sys.stderr)
