"""Notifiers: none (default), slack (webhook), email (SMTP).

Credentials come from the environment only. A notifier that cannot run says so
and returns — a failed notification never fails the run that produced a brief.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Protocol

import httpx

from .config import Config
from .util import log, one_line


class _Result(Protocol):
    date: object
    text: str
    streams: list
    mind: object


def _summary_lines(cfg: Config, res) -> tuple[str, str]:
    title = f"Lumina Daily — {res.date}"
    parts = []
    if getattr(res, "mind", None):
        parts.append(f"*Mind:* {res.mind.item.title}")
        if res.mind.key_idea:
            parts.append(f"> {one_line(res.mind.key_idea, 180)}")
    if res.streams:
        parts.append("*Streams:*")
        for s in res.streams:
            parts.append(f"• {one_line(s.opportunity, 90)} — *{s.total}/10* (`{s.rung}`)")
    else:
        parts.append("_No stream signal cleared the bar today._")
    repo = os.getenv("GITHUB_REPOSITORY")
    if repo:
        parts.append(f"\nhttps://github.com/{repo}/blob/main/daily/{res.date}.md")
    return title, "\n".join(parts)


def notify_none(cfg: Config, res) -> bool:
    log.debug("notifier disabled")
    return True


def notify_slack(cfg: Config, res) -> bool:
    webhook = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook:
        log.warning("notify.channel is slack but SLACK_WEBHOOK_URL is not set — skipping")
        return False
    title, body = _summary_lines(cfg, res)
    payload = {
        "username": cfg.get("notify.slack.username", "Lumina Daily"),
        "icon_emoji": cfg.get("notify.slack.icon_emoji", ":sunrise:"),
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "section", "text": {"type": "mrkdwn", "text": body[:2900]}},
        ],
    }
    try:
        resp = httpx.post(webhook, json=payload, timeout=15)
        resp.raise_for_status()
        log.info("notified slack")
        return True
    except Exception as exc:
        log.warning("slack notification failed (%s) — the brief is still written", exc)
        return False


def notify_email(cfg: Config, res) -> bool:
    host = os.getenv("SMTP_HOST")
    to_addr = cfg.get("notify.email.to") or os.getenv("SMTP_TO")
    from_addr = cfg.get("notify.email.from") or os.getenv("SMTP_USER")
    if not (host and to_addr and from_addr):
        log.warning("notify.channel is email but SMTP_HOST / to / from are incomplete — skipping")
        return False
    title, _ = _summary_lines(cfg, res)
    msg = EmailMessage()
    msg["Subject"] = f"{cfg.get('notify.email.subject_prefix', '[Lumina]')} {title}"
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(res.text)
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls()
            user, password = os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD")
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        log.info("emailed %s", to_addr)
        return True
    except Exception as exc:
        log.warning("email notification failed (%s) — the brief is still written", exc)
        return False


NOTIFIERS = {"none": notify_none, "slack": notify_slack, "email": notify_email}


def notify(cfg: Config, res, override: str | None = None) -> bool:
    channel = (override or cfg.get("notify.channel", "none") or "none").lower()
    fn = NOTIFIERS.get(channel)
    if fn is None:
        log.warning("unknown notify channel %r — nothing sent", channel)
        return False
    return fn(cfg, res)
