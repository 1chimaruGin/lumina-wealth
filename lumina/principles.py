"""Parsing curriculum/principles.md and choosing the day's principle."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .state import PrincipleLog

_HEADING = re.compile(r"^##\s+(?P<id>[A-Za-z0-9_-]+)\s*[·|:—-]\s*(?P<title>.+?)\s*$", re.M)
_META = re.compile(r"<!--\s*source:\s*(?P<source>[^|]+?)\s*(?:\|\s*tags:\s*(?P<tags>[^>]*?))?\s*-->")
_PROMPT = re.compile(r"\*\*Prompt:\*\*\s*(?P<prompt>.+?)\s*$", re.M)


@dataclass
class Principle:
    id: str
    title: str
    source: str
    tags: list[str]
    body: str
    prompt: str


def parse_principles(path: Path | str) -> list[Principle]:
    path = Path(path)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    matches = list(_HEADING.finditer(text))
    out: list[Principle] = []
    for i, m in enumerate(matches):
        chunk = text[m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        meta = _META.search(chunk)
        prompt = _PROMPT.search(chunk)
        body = _META.sub("", chunk)
        body = _PROMPT.sub("", body)
        body = re.sub(r"\n-{3,}\n", "\n", body).strip()
        out.append(
            Principle(
                id=m.group("id"),
                title=m.group("title").strip(),
                source=(meta.group("source").strip() if meta else ""),
                tags=[t.strip() for t in (meta.group("tags") or "").split(",") if t.strip()] if meta else [],
                body=body,
                prompt=(prompt.group("prompt").strip() if prompt else ""),
            )
        )
    return out


def pick_principle(
    principles: list[Principle], plog: PrincipleLog, on: date, cooldown_days: int = 21
) -> Principle | None:
    """Spaced repetition.

    Prefer anything never shown, then anything outside the cooldown window
    (oldest first). If everything is inside the window — which happens when
    there are fewer principles than cooldown days — fall back to the
    least-recently-shown, so the brief always has a principle.

    Seeded by the date so a given day always resurfaces the same principle,
    which keeps a re-run idempotent.
    """
    if not principles:
        return None

    never = [p for p in principles if plog.last_shown(p.id) is None]
    if never:
        return random.Random(on.toordinal()).choice(never)

    cutoff = on - timedelta(days=cooldown_days)
    eligible = [p for p in principles if (plog.last_shown(p.id) or date.min) <= cutoff]
    pool = eligible or principles
    pool = sorted(pool, key=lambda p: (plog.last_shown(p.id) or date.min, p.id))
    oldest = pool[0]
    tied = [p for p in pool if plog.last_shown(p.id) == plog.last_shown(oldest.id)]
    return random.Random(on.toordinal()).choice(tied)
