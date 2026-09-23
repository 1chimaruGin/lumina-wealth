#!/usr/bin/env python3
"""The one-stream-at-a-time CLI.

    stream.py status                 what is running, and how far in
    stream.py activate               start a stream — refused if the slot is taken
    stream.py log                    record an action, minutes, revenue, or a note
    stream.py gate-check             can you start something new yet?
    stream.py graduate               route A: it earns — free the slot, keep it running
    stream.py archive                route B: it is over — file the decision, free the slot

The gate is the point. Everything else is bookkeeping that feeds it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lumina.config import load_config  # noqa: E402
from lumina.rubric import RUNGS  # noqa: E402
from lumina.streams import (  # noqa: E402
    Stream, archive_path, check_gate, load_stream, save_stream,
)
from lumina.util import parse_date, slugify, today, write_text, yen  # noqa: E402

GREEN, RED, DIM, BOLD, OFF = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def _c(text: str, colour: str) -> str:
    return f"{colour}{text}{OFF}" if sys.stdout.isatty() else text


ACTIVE_BODY = """# Active stream — {name}

**Rung:** `{rung}` · **Started:** {started} · **Goal:** {goal}
**Weekly metric:** {metric}

## Next actions

{actions}

## How this ends

One of two ways, and `stream.py gate-check` will tell you which you are near:

- **It works.** First revenue plus a routine that held → `stream.py graduate`.
  The stream keeps running from `streams/running/`, and the build slot frees up.
- **It does not.** {cycle} days done → `stream.py archive --decision kill|pivot`,
  which makes you write down what you learned before you are allowed to move on.

Until then this is the only stream you are building. Ideas still go to
`ideas/inbox/` — capturing is free, starting is not.
"""


def cmd_status(cfg, args) -> int:
    s = load_stream(cfg.active_stream_file)
    if not s.active:
        print(f"{_c('No active stream.', BOLD)} The slot is open.\n")
        print("  Activate one:  python scripts/stream.py activate --name \"...\" \\")
        print("                   --rung 1-skills --goal \"...\" --metric \"...\"")
        running = sorted((cfg.streams_dir / "running").glob("*.md")) if (cfg.streams_dir / "running").exists() else []
        if running:
            print(f"\n  Still earning ({len(running)}): " + ", ".join(p.stem for p in running))
        return 0
    d = today()
    print(f"\n  {_c(s.name, BOLD)}  `{s.rung}`")
    print(f"  Day {s.day_number(d)} of {s.cycle_days}   ({s.days_remaining(d)} left)")
    print(f"  Revenue      {yen(s.revenue_to(d))}")
    print(f"  Goal         {s.goal or '—'}")
    print(f"  Metric       {s.weekly_metric or 'actions logged per week'} — {s.metric_value(d)}")
    print(f"  Logged       {s.logged_days()} days, {len([e for e in s.log if e.get('action')])} actions")
    if s.next_actions:
        print(f"  Next         {s.next_actions[0]}")
    print()
    return cmd_gate_check(cfg, args, quiet_header=True)


def cmd_gate_check(cfg, args, quiet_header: bool = False) -> int:
    s = load_stream(cfg.active_stream_file)
    result = check_gate(s, cfg.get("stream.gate"), on=today())
    print(_c(result.render(), GREEN if result.passed else RED))
    print()
    for reason in result.reasons:
        print(f"  {reason}")
    if result.passed and s.active:
        nxt = "graduate" if result.route == "A" else "archive --decision kill|pivot"
        print(f"\n  Next: python scripts/stream.py {nxt}")
    print()
    return 0 if result.passed else 1


def cmd_activate(cfg, args) -> int:
    current = load_stream(cfg.active_stream_file)
    if current.active:
        result = check_gate(current, cfg.get("stream.gate"), on=today())
        print(_c(f"Refused — '{current.name}' is still active.", RED))
        print("\n  One stream at a time. That rule is the whole system.\n")
        for reason in result.reasons:
            print(f"  {reason}")
        if result.passed:
            nxt = "graduate" if result.route == "A" else "archive --decision kill|pivot"
            print(f"\n  It has passed the gate — free the slot first:\n    python scripts/stream.py {nxt}")
        print(f"\n  Your idea is safe in ideas/inbox/. Capture is free; starting is not.\n")
        return 2

    started = parse_date(args.start) or today()
    stream = Stream(
        status="active",
        name=args.name,
        slug=slugify(args.name),
        rung=args.rung,
        started=started,
        cycle_days=int(args.cycle or cfg.get("stream.cycle_days", 90)),
        goal=args.goal,
        weekly_metric=args.metric,
        revenue_jpy=0,
        gate_passed=False,
        next_actions=list(args.action or []),
        log=[],
    )
    actions = "\n".join(f"- [ ] {a}" for a in stream.next_actions) or "- [ ] _Add the first one with `--action` or by editing this file._"
    body = ACTIVE_BODY.format(
        name=stream.name, rung=stream.rung, started=started, goal=stream.goal or "—",
        metric=stream.weekly_metric or "actions logged per week", actions=actions, cycle=stream.cycle_days,
    )
    save_stream(cfg.active_stream_file, stream, body)
    print(_c(f"\n  Activated: {stream.name}", GREEN))
    print(f"  Rung {stream.rung} · day 1 of {stream.cycle_days} · goal: {stream.goal or '—'}")
    print(f"\n  Tomorrow's brief will carry an action for it.")
    print(f"  Log your first rep: python scripts/stream.py log --action \"...\" --minutes 10\n")
    return 0


def cmd_log(cfg, args) -> int:
    s = load_stream(cfg.active_stream_file)
    if not s.active:
        print(_c("No active stream to log against.", RED))
        print("  Activate one first: python scripts/stream.py activate --help\n")
        return 2
    if not (args.action or args.revenue or args.note):
        print(_c("Nothing to log.", RED), "Give at least one of --action, --revenue, --note.\n")
        return 2

    when = parse_date(args.date) or today()
    entry = {"date": str(when)}
    if args.action:
        entry["action"] = args.action
    if args.minutes:
        entry["minutes"] = int(args.minutes)
    if args.revenue:
        entry["revenue"] = int(args.revenue)
    if args.note:
        entry["note"] = args.note
    s.log.append(entry)
    s.log.sort(key=lambda e: str(e.get("date")))
    s.revenue_jpy = sum(int(e.get("revenue") or 0) for e in s.log)
    save_stream(cfg.active_stream_file, s)

    bits = []
    if args.action:
        bits.append(f"action: {args.action}")
    if args.minutes:
        bits.append(f"{args.minutes} min")
    if args.revenue:
        bits.append(_c(f"+{yen(args.revenue)}", GREEN))
    if args.note:
        bits.append(f"note: {args.note}")
    print(f"\n  Logged for {when} — " + " · ".join(bits))
    print(f"  {s.logged_days()} days logged · {yen(s.revenue_jpy)} total\n")

    if args.revenue and s.revenue_jpy == int(args.revenue):
        print(_c("  First revenue. That is route A opening up.", GREEN))
        print("  Keep the routine going, then: python scripts/stream.py gate-check\n")
    return 0


def _retire(cfg, args, decision: str, required_route: str | None) -> int:
    s = load_stream(cfg.active_stream_file)
    if not s.active:
        print(_c("No active stream.", RED), "Nothing to retire.\n")
        return 2
    result = check_gate(s, cfg.get("stream.gate"), on=today())
    if not result.passed and not args.force:
        print(_c(f"Refused — '{s.name}' has not passed the gate.", RED))
        print()
        for reason in result.reasons:
            print(f"  {reason}")
        print("\n  Quitting early is the pattern this system exists to interrupt.")
        print("  If you are genuinely sure, re-run with --force --reason \"...\".\n")
        return 2
    if required_route and result.route != required_route and not args.force:
        other = "archive --decision kill|pivot" if required_route == "A" else "graduate"
        print(_c(f"Refused — this stream passed the gate by route {result.route}, not {required_route}.", RED))
        print(f"\n  Use: python scripts/stream.py {other}\n")
        return 2

    on = today()
    day_n = s.day_number(on) or 0
    dest_dir = cfg.streams_dir / ("running" if decision == "graduate" else "archive")
    dest = dest_dir / f"{on}-{s.slug}.md" if decision == "graduate" else archive_path(cfg.root, s, on)

    meta = s.to_meta()
    meta["status"] = "running" if decision == "graduate" else decision
    meta["gate_passed"] = result.passed
    meta["gate_route"] = result.route or ("forced" if args.force else None)
    meta["ended"] = str(on)
    meta["days_run"] = day_n

    verdict = args.reason or args.notes or ""
    title = {"graduate": "Graduated", "kill": "Killed", "pivot": "Pivoted"}[decision]
    body = f"""# {title} — {s.name}

**Ran:** {s.started} → {on} ({day_n} days of {s.cycle_days}) · **Rung:** `{s.rung}`
**Revenue:** {yen(s.revenue_jpy)} · **Goal was:** {s.goal or '—'}
**Gate:** {'passed via route ' + result.route if result.passed else 'FORCED — did not pass'}

## Decision

{verdict or '_No reason recorded. Write one — this file is the only thing that stops the next stream repeating this one._'}

## What the numbers said

- {s.logged_days()} days logged, {len([e for e in s.log if e.get('action')])} actions
- {yen(s.revenue_jpy)} earned
- Metric: {s.weekly_metric or 'actions logged per week'}

## Log

{chr(10).join(f"- **{e.get('date')}** — {e.get('action') or e.get('note') or 'logged'}" + (f" ({e['minutes']} min)" if e.get('minutes') else "") + (f" · +{yen(e['revenue'])}" if e.get('revenue') else "") for e in s.log) or '_Nothing was logged. That is itself the finding._'}
"""
    from lumina.streams import join_frontmatter
    write_text(dest, join_frontmatter(meta, body))

    empty = Stream()
    save_stream(
        cfg.active_stream_file, empty,
        Path(cfg.root / "streams" / ".empty_body.md").read_text(encoding="utf-8")
        if (cfg.root / "streams" / ".empty_body.md").exists()
        else EMPTY_BODY,
    )
    print(_c(f"\n  {title}: {s.name}", GREEN))
    print(f"  Written to {dest.relative_to(cfg.root)}")
    print(f"  The slot is now open.\n")
    if decision == "graduate":
        print("  It keeps earning from streams/running/. Nothing about it is automated —")
        print("  log revenue against it by hand if you want the dashboard to know.\n")
    print("  Next: the weekly digest ranks your inbox. Pick one and activate it.\n")
    return 0


EMPTY_BODY = """# Active stream — none

No stream is active. Exactly one may be, by design.

Pick a candidate from `ideas/inbox/` — the weekly digest ranks the top 5 — and:

```bash
python scripts/stream.py activate --name "..." --rung 1-skills \\
  --goal "..." --metric "..."
```
"""


def cmd_graduate(cfg, args) -> int:
    return _retire(cfg, args, "graduate", required_route="A")


def cmd_archive(cfg, args) -> int:
    return _retire(cfg, args, args.decision, required_route=None)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stream.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="what is running, and how far in")
    sub.add_parser("gate-check", help="can you start something new yet?")

    a = sub.add_parser("activate", help="start a stream (refused if the slot is taken)")
    a.add_argument("--name", required=True)
    a.add_argument("--rung", required=True, choices=list(RUNGS))
    a.add_argument("--goal", required=True, help='e.g. "¥100,000 in 90 days"')
    a.add_argument("--metric", required=True, help='the weekly number, e.g. "outreach conversations"')
    a.add_argument("--start", help="YYYY-MM-DD (default: today)")
    a.add_argument("--cycle", type=int, help="cycle length in days (default: 90)")
    a.add_argument("--action", action="append", help="a next action; repeatable")

    l = sub.add_parser("log", help="record an action, minutes, revenue, or a note")
    l.add_argument("--action")
    l.add_argument("--minutes", type=int)
    l.add_argument("--revenue", type=int, help="JPY received")
    l.add_argument("--note")
    l.add_argument("--date", help="YYYY-MM-DD (default: today)")

    g = sub.add_parser("graduate", help="route A: it earns — free the slot, keep it running")
    g.add_argument("--reason", help="what made it work")
    g.add_argument("--notes")
    g.add_argument("--force", action="store_true")

    ar = sub.add_parser("archive", help="route B: it is over — file the decision, free the slot")
    ar.add_argument("--decision", required=True, choices=["kill", "pivot"])
    ar.add_argument("--reason", help="what you learned; required in spirit, enforced by your own honesty")
    ar.add_argument("--notes")
    ar.add_argument("--force", action="store_true", help="retire a stream that has not passed the gate")
    return p


COMMANDS = {
    "status": cmd_status, "gate-check": cmd_gate_check, "activate": cmd_activate,
    "log": cmd_log, "graduate": cmd_graduate, "archive": cmd_archive,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config()
    return COMMANDS[args.command](cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
