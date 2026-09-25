"""Composition: turn collected + scored material into the brief and the digest."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .config import Config
from .principles import Principle
from .rubric import CRITERIA
from .score import MindPiece, StreamScore
from .streams import Stream, check_gate, split_frontmatter
from .util import JST, iso_week, now, one_line, shorten, week_bounds, write_text, yen

# Fallback actions when next_actions is empty — 5-15 minutes, rung-appropriate,
# and deliberately small enough that "no time today" is not a valid excuse.
DEFAULT_ACTIONS = {
    "1-skills": [
        "Send one message to someone who has the problem you solve. Ask about last time it bit them.",
        "Write three sentences describing exactly who you help and what breaks without you.",
        "List five people who could introduce you to a paying client. Pick one and message them.",
        "Raise your stated rate by 20% in your own notes and read it out loud until it stops feeling absurd.",
    ],
    "2-productized": [
        "Write the fixed scope of your offer as a bullet list a buyer could say yes to in one read.",
        "Price the offer. One number, one deliverable, one turnaround. No options.",
        "Find one past conversation where someone asked for this and reply to it.",
        "Write the one-paragraph sales page. Ugly is fine, vague is not.",
    ],
    "3-product": [
        "Ship the smallest change a user would notice. Fifteen minutes, then stop.",
        "Message one user and ask what they did right before they signed up.",
        "Write the landing page headline as a sentence about their problem, not your feature.",
        "Cut one feature from the plan. Write down why it can wait.",
    ],
    "4-assets": [
        "Write down what this asset earns without you touching it, and what breaks first if you stop.",
        "Automate one manual step you did this week.",
        "Document the one process only you know how to run.",
    ],
    None: [
        "Pick one idea from the inbox and write why it is not a good fit. Clarity beats another idea.",
    ],
}


def env_for(cfg: Config) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(cfg.template_dir)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["yen"] = yen
    env.filters["shorten"] = shorten
    return env


def todays_action(stream: Stream, on: date) -> str:
    """One task, chosen deterministically so re-running a date is idempotent.

    Explicit next_actions win; otherwise a rung-appropriate default rotates.
    """
    if stream.next_actions:
        idx = on.toordinal() % len(stream.next_actions)
        return str(stream.next_actions[idx])
    pool = DEFAULT_ACTIONS.get(stream.rung) or DEFAULT_ACTIONS[None]
    return pool[on.toordinal() % len(pool)]


def compose_daily(
    cfg: Config,
    d: date,
    mind: MindPiece | None,
    streams: list[StreamScore],
    principle: Principle | None,
    stream: Stream,
    *,
    mode: str = "daily",
    lessons: list | None = None,
    extra_reading: list | None = None,
    book=None,
    news: list | None = None,
    news_ignored: str = "",
    sources_ok: int = 0,
    sources_total: int = 0,
    sources_failed: list[dict] | None = None,
    notes: list[str] | None = None,
    scored_by: str = "heuristic",
    cost: str = "",
    filed: int = 0,
) -> str:
    gate = check_gate(stream, cfg.get("stream.gate"), on=d)
    if not stream.active:
        gate_line = "slot open"
    elif gate.passed:
        gate_line = f"**passed** (route {gate.route}) — you may activate the next stream"
    else:
        gate_line = f"not passed — {one_line(gate.reasons[0], 120)}"

    template = env_for(cfg).get_template("daily.md.j2")
    return template.render(
        d=str(d),
        date_obj=d,
        weekday=d.strftime("%A"),
        pretty_date=d.strftime("%A, %-d %B %Y"),
        week=iso_week(d),
        generated_at=now().isoformat(timespec="seconds"),
        mode=mode,
        lessons=lessons or [],
        extra_reading=extra_reading or [],
        book=book,
        news=news or [],
        news_ignored=news_ignored,
        mind=mind,
        streams=streams,
        principle=principle,
        stream=stream,
        criteria=CRITERIA,
        action=todays_action(stream, d),
        revenue=yen(stream.revenue_to(d)),
        gate_line=gate_line,
        min_score=cfg.get("select.min_stream_score", 4.5),
        show_streams=bool(cfg.get("select.show_streams_in_daily", False)),
        sources_ok=sources_ok,
        sources_total=sources_total,
        sources_failed=sources_failed or [],
        notes=notes or [],
        scored_by=scored_by,
        cost=cost,
        filed=filed,
    )


# --- weekly -----------------------------------------------------------------


def read_brief_meta(path: Path) -> dict:
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
    meta["_body"] = body
    meta["_path"] = path
    return meta


def load_week_briefs(cfg: Config, start: date, end: date) -> list[dict]:
    out = []
    for path in sorted(cfg.daily_dir.glob("*.md")):
        stem = path.stem
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", stem):
            continue
        d = date.fromisoformat(stem)
        if start <= d <= end:
            out.append(read_brief_meta(path))
    return out


def load_inbox(cfg: Config, limit: int = 5, since: date | None = None) -> list[dict]:
    """Rank inbox ideas for the NEXT slot. Status must still be 'inbox' — once
    you triage an idea by hand, it stops competing."""
    ideas = []
    for path in cfg.inbox_dir.glob("*.md"):
        try:
            meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not meta or meta.get("status") not in (None, "inbox"):
            continue
        captured = meta.get("captured") or meta.get("date")
        verdict = ""
        m = re.search(r"\*\*Rung:\*\*.*?\n\n(.+?)\n", body, re.S)
        if m:
            verdict = one_line(m.group(1).strip(), 200)
        ideas.append(
            {
                "title": meta.get("title", path.stem),
                "url": meta.get("url", ""),
                "rung": meta.get("rung", "?"),
                "score": meta.get("score", 0),
                "captured": str(captured or ""),
                "verdict": verdict or "No verdict recorded.",
                "path": path,
            }
        )
    ideas.sort(key=lambda i: (float(i["score"] or 0), str(i["captured"])), reverse=True)
    return ideas[:limit]


def best_mind_of_week(briefs: list[dict]) -> dict | None:
    """The Mind piece whose key idea is the most substantial. With no quality
    signal to rank on, length of the stated key idea is the honest proxy — and
    it is stated as a heuristic rather than dressed up as judgment."""
    best = None
    for b in briefs:
        m = re.search(r"## 1 · Mind\s*\n+### \[(?P<title>.+?)\]\((?P<url>.+?)\)", b.get("_body", ""), re.S)
        if not m:
            continue
        key = re.search(r"> \*\*Key idea\.\*\* (.+?)\n", b.get("_body", ""))
        cand = {
            "title": m.group("title"),
            "url": m.group("url"),
            "source": b.get("mind_source", ""),
            "date": b.get("date", ""),
            "key_idea": (key.group(1).strip() if key else ""),
        }
        if best is None or len(cand["key_idea"]) > len(best["key_idea"]):
            best = cand
    return best


REFLECTIONS = [
    "Which of this week's actions would you have skipped if nobody was keeping score — and what does that tell you?",
    "You captured ideas this week and activated none of them. Was that discipline, or avoidance?",
    "What is the smallest piece of evidence you got this week that someone will actually pay?",
    "If this stream earns nothing in the next 30 days, what will you wish you had tested first?",
    "Which felt better this week: finishing something small, or planning something big? Which moved the number?",
    "What did you avoid this week because it risked a no?",
]


def week_lessons(cfg: Config, briefs: list[dict]) -> list[dict]:
    """The lessons taught this week, read back from the cached lesson files.

    The digest is now the only weekly summary of what was actually learned, so
    it reads the real lessons rather than re-deriving them.
    """
    from .curriculum import load_syllabus, lesson_path, load_lesson

    syllabus = load_syllabus(cfg.root / cfg.get("curriculum.syllabus", "curriculum/syllabus.yaml"))
    out = []
    for brief in briefs:
        raw = brief.get("lesson_ids") or []
        ids = raw if isinstance(raw, list) else [s.strip() for s in str(raw).strip("[]").split(",") if s.strip()]
        for tid in ids:
            topic = syllabus.topic(str(tid).strip())
            if not topic:
                continue
            lesson = load_lesson(cfg.root, topic)
            out.append({
                "id": topic.id, "title": topic.title, "track": topic.track,
                "track_name": topic.track_name, "date": str(brief.get("date", "")),
                "key_idea": lesson.key_idea if lesson else "",
            })
    return out


def compose_weekly(
    cfg: Config,
    end: date,
    stream: Stream,
    briefs: list[dict],
    top_ideas: list[dict],
) -> str:
    start, _ = week_bounds(end)
    gate = check_gate(stream, cfg.get("stream.gate"), on=end)
    gate_line = (
        "slot open" if not stream.active
        else (f"**passed** (route {gate.route})" if gate.passed else f"not passed — {one_line(gate.reasons[0], 110)}")
    )

    week_log = [e for e in stream.log if e.get("date") and start <= date.fromisoformat(str(e["date"])[:10]) <= end]
    week_revenue = sum(int(e.get("revenue") or 0) for e in week_log)
    have = {b.get("date") for b in briefs}
    missing = [str(start.fromordinal(o)) for o in range(start.toordinal(), end.toordinal() + 1)
               if str(start.fromordinal(o)) not in have]

    lessons = week_lessons(cfg, briefs)
    tracks_covered = sorted({l["track_name"] for l in lessons})
    template = env_for(cfg).get_template("weekly.md.j2")
    return template.render(
        lessons=lessons,
        tracks_covered=tracks_covered,
        week=iso_week(end),
        start=str(start),
        end=str(end),
        end_obj=end,
        generated_at=now().isoformat(timespec="seconds"),
        briefs=briefs,
        top_ideas=top_ideas,
        stream=stream,
        revenue=yen(stream.revenue_to(end)),
        week_revenue=yen(week_revenue) if week_revenue else "",
        week_actions=len([e for e in week_log if e.get("action")]),
        week_log=week_log,
        gate_line=gate_line,
        best_mind=best_mind_of_week(briefs),
        reflection=REFLECTIONS[end.isocalendar()[1] % len(REFLECTIONS)],
        principles_shown=sorted({b.get("principle") for b in briefs if b.get("principle") and b.get("principle") != "none"}),
        missing_days=missing,
    )
