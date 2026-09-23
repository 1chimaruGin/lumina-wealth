"""Build the dashboard: site/index.html, self-contained, no network needed.

The data is inlined into the page rather than fetched, so the same file works
from GitHub Pages, from a file:// path, and from anywhere else you drop it.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from .config import Config
from .markdown import render as render_md
from .principles import parse_principles
from .state import PrincipleLog
from .streams import check_gate, load_stream, split_frontmatter
from .util import iso_week, log, now, read_jsonl, today, write_text, yen


def _meta_of(path: Path) -> tuple[dict, str]:
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return (meta or {}), body


def collect_data(cfg: Config) -> dict:
    d = today()
    stream = load_stream(cfg.active_stream_file)
    gate = check_gate(stream, cfg.get("stream.gate"), on=d)

    briefs = []
    for path in sorted(cfg.daily_dir.glob("*.md"), reverse=True):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
            continue
        meta, body = _meta_of(path)
        briefs.append({
            "date": str(meta.get("date") or path.stem),
            "weekday": meta.get("weekday", ""),
            "week": str(meta.get("week", "")),
            "mode": meta.get("mode", "daily"),
            "mind_source": meta.get("mind_source", ""),
            "top_score": float(meta.get("top_score") or 0),
            "stream_count": int(meta.get("stream_count") or 0),
            "sources_ok": int(meta.get("sources_ok") or 0),
            "sources_failed": int(meta.get("sources_failed") or 0),
            "scored_by": meta.get("scored_by", ""),
            "principle": str(meta.get("principle", "")),
            "html": render_md(body),
        })
    briefs = briefs[: int(cfg.get("site.recent_briefs", 30))]

    digests = []
    for path in sorted(cfg.digest_dir.glob("*.md"), reverse=True)[:12]:
        meta, body = _meta_of(path)
        digests.append({
            "week": str(meta.get("week") or path.stem),
            "start": str(meta.get("start", "")),
            "end": str(meta.get("end", "")),
            "html": render_md(body),
        })

    inbox = []
    for path in cfg.inbox_dir.glob("*.md"):
        meta, body = _meta_of(path)
        if not meta:
            continue
        opp = re.search(r"\*\*Opportunity:\*\*\s*(.+)", body)
        verdict = re.search(r"\*\*Score:\*\*.*?\n\n(.+?)\n", body, re.S)
        inbox.append({
            "title": meta.get("title", path.stem),
            "opportunity": (opp.group(1).strip() if opp else meta.get("title", "")),
            "url": meta.get("url", ""),
            "rung": meta.get("rung", "?"),
            "score": float(meta.get("score") or 0),
            "status": meta.get("status", "inbox"),
            "captured": str(meta.get("captured") or meta.get("date") or ""),
            "source": meta.get("source", ""),
            "verdict": (verdict.group(1).strip() if verdict else ""),
        })
    inbox.sort(key=lambda i: (i["score"], i["captured"]), reverse=True)

    plog = PrincipleLog.load(cfg.data_dir)
    principles = [
        {"id": p.id, "title": p.title, "source": p.source,
         "last": str(plog.last_shown(p.id) or ""), "seen": plog.last_shown(p.id) is not None}
        for p in parse_principles(cfg.principles_file)
    ]

    # Last 21 days of logged activity — the streak strip.
    activity = []
    for offset in range(20, -1, -1):
        day = d - timedelta(days=offset)
        entries = stream.actions_on(day) if stream.active else []
        activity.append({
            "date": str(day),
            "actions": len([e for e in entries if e.get("action")]),
            "minutes": sum(int(e.get("minutes") or 0) for e in entries),
            "revenue": sum(int(e.get("revenue") or 0) for e in entries),
            "brief": any(b["date"] == str(day) for b in briefs),
        })

    running = []
    running_dir = cfg.streams_dir / "running"
    if running_dir.exists():
        for path in sorted(running_dir.glob("*.md")):
            meta, _ = _meta_of(path)
            running.append({"name": meta.get("name", path.stem), "rung": meta.get("rung", ""),
                            "revenue_jpy": int(meta.get("revenue_jpy") or 0), "ended": str(meta.get("ended", ""))})

    archived = []
    for path in sorted((cfg.streams_dir / "archive").glob("*.md"), reverse=True):
        meta, _ = _meta_of(path)
        if meta:
            archived.append({"name": meta.get("name", path.stem), "status": meta.get("status", ""),
                             "days_run": int(meta.get("days_run") or 0), "ended": str(meta.get("ended", ""))})

    runs = read_jsonl(cfg.data_dir / "runs.jsonl")[-30:]

    return {
        "generated_at": now().isoformat(timespec="minutes"),
        "today": str(d),
        "title": cfg.get("site.title", "Lumina Daily"),
        "tagline": cfg.get("site.tagline", ""),
        "stream": {
            "active": stream.active,
            "name": stream.name,
            "rung": stream.rung,
            "started": str(stream.started or ""),
            "day": stream.day_number(d) or 0,
            "cycle": stream.cycle_days,
            "revenue_jpy": stream.revenue_to(d) if stream.active else 0,
            "revenue": yen(stream.revenue_to(d)) if stream.active else yen(0),
            "goal": stream.goal or "",
            "metric": stream.weekly_metric or "actions logged per week",
            "metric_value": stream.metric_value(d) if stream.active else "",
            "logged_days": stream.logged_days(),
            "actions": len([e for e in stream.log if e.get("action")]),
            "next_actions": stream.next_actions,
        },
        "gate": {
            "passed": gate.passed,
            "route": gate.route,
            "reasons": gate.reasons,
            "checks": [{"label": l, "ok": ok, "detail": det} for l, ok, det in gate.checks],
        },
        "running": running,
        "archived": archived,
        "briefs": briefs,
        "digests": digests,
        "inbox": inbox,
        "principles": principles,
        "activity": activity,
        "runs": runs,
        "sources": {
            "enabled": [{"id": s.id, "name": s.name, "section": s.section, "backfill": s.backfill}
                        for s in cfg.enabled_sources()],
            "disabled": [{"id": s.id, "name": s.name, "reason": " ".join((s.disabled_reason or "").split())}
                         for s in cfg.disabled_sources()],
        },
    }


def build_site(cfg: Config, out: Path | None = None, fragment: bool = False) -> Path:
    """fragment=True emits the page without the <html>/<head>/<body> wrapper,
    for hosts that supply their own document skeleton."""
    from .compose import env_for

    data = collect_data(cfg)
    template = env_for(cfg).get_template("site/index.html.j2")
    html = template.render(
        data=data,
        fragment=fragment,
        data_json=json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
    )
    path = write_text(out or (cfg.root / "site" / "index.html"), html)
    log.info("built %s (%.0f KB)", path, path.stat().st_size / 1024)
    return path
