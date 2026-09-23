"""Small shared helpers: dates in JST, slugs, atomic writes, logging."""

from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
import tempfile
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
JST = ZoneInfo("Asia/Tokyo")

log = logging.getLogger("lumina")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    # feedparser and httpx are chatty at DEBUG and tell us nothing useful.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


# --- dates -----------------------------------------------------------------
# Every date in this system is a JST calendar date. Filenames, "day N of 90",
# and the daily window all agree because they all come through here.


def now(tz: ZoneInfo = JST) -> datetime:
    return datetime.now(tz)


def today(tz: ZoneInfo = JST) -> date:
    return now(tz).date()


def parse_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.astimezone(JST).date()
    return date.fromisoformat(str(value).strip()[:10])


def day_bounds(d: date, tz: ZoneInfo = JST) -> tuple[datetime, datetime]:
    """UTC-aware [start, end) covering the local calendar day `d`."""
    start = datetime.combine(d, time.min, tzinfo=tz)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def to_jst(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(JST)


def iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def week_bounds(d: date) -> tuple[date, date]:
    """Monday..Sunday of the ISO week containing `d`."""
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def daterange(start: date, end: date):
    """Inclusive, ascending. Backfill runs oldest-first so dedupe and the
    principle rotation replay in the order they really happened."""
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


# --- text ------------------------------------------------------------------


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0]
    return text or "untitled"


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    # unescape handles named and numeric entities alike; feeds emit both.
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def clip_words(text: str, max_words: int) -> str:
    """Copyright guard. Source text is only ever held long enough to be scored,
    and never at a length that could stand in for the article."""
    words = strip_html(text).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",.;:") + "…"


def shorten(text: str, max_chars: int = 70) -> str:
    """Trim to a word boundary. A name cut mid-word reads as a bug, and this
    text gets pasted straight into a command."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:—-")


def one_line(text: str, max_chars: int = 200) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def yen(amount: float | int | None) -> str:
    if not amount:
        return "¥0"
    return f"¥{int(amount):,}"


# --- io --------------------------------------------------------------------


def read_json(path: Path | str, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8") or "null")
    except json.JSONDecodeError:
        log.warning("%s is not valid JSON; starting from default", path)
        return default


def write_json(path: Path | str, data: Any) -> None:
    """Atomic: a killed run never leaves half a state file behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True, default=str)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_text(path: Path | str, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
    return path


def append_jsonl(path: Path | str, record: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def read_jsonl(path: Path | str) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
