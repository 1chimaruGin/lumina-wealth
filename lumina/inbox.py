"""Writing scored opportunities to ideas/inbox/.

Nothing here activates anything. Capture is free, activation is gated — that
split is the whole point of the inbox.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from .rubric import CRITERIA, verdict_band
from .score import StreamScore
from .util import slugify, today, write_text


def inbox_path(inbox_dir: Path, score: StreamScore) -> Path:
    return Path(inbox_dir) / f"{slugify(score.item.title)}.md"


def render_idea(score: StreamScore, captured: date | None = None) -> str:
    meta = score.to_frontmatter()
    meta["captured"] = str(captured or today())
    fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip()

    rows = "\n".join(
        f"| {c.label} | {int(c.weight * 100)}% | {score.scores.get(c.key, 5)}/10 |" for c in CRITERIA
    )
    band, action = verdict_band(score.total)
    item = score.item
    return f"""---
{fm}
---

# {item.title}

**Opportunity:** {score.opportunity}
**Rung:** `{score.rung}` · **Score:** {score.total}/10 ({band})

{score.verdict}

**Demand signal:** {score.why_now or "none recorded"}

| Criterion | Weight | Score |
|---|---|---|
{rows}

**Next step if activated:** {action}

Source: [{item.source_name}]({item.url}){f" · {item.points} points" if item.points else ""}
"""


def save_ideas(inbox_dir: Path, scores: list[StreamScore], captured: date | None = None) -> list[Path]:
    """Write one file per opportunity. Never overwrites an idea you have
    already triaged — status changes you make by hand are yours to keep."""
    written = []
    for score in scores:
        path = inbox_path(inbox_dir, score)
        if path.exists():
            continue
        write_text(path, render_idea(score, captured))
        written.append(path)
    return written
