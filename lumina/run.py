"""The pipeline: collect → classify → score → select → compose → save → notify."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .classify import classify_all, prefilter
from .collect import collect_all, dedupe, within_lookback
from .compose import compose_daily, compose_weekly, load_inbox, load_week_briefs
from .curriculum import CurriculumState, get_or_write_lesson, load_syllabus, next_topics
from .config import Config, load_config
from .inbox import save_ideas
from .principles import parse_principles, pick_principle
from .score import HeuristicScorer, MindPiece, StreamScore, build_scorer
from .state import PrincipleLog, SeenStore, UsageStore, log_run
from .streams import load_stream
from .util import (ROOT, append_jsonl, daterange, iso_week, log, read_jsonl, setup_logging,
                   today, week_bounds, write_text)


@dataclass
class DailyResult:
    date: date
    path: Path | None
    text: str
    mind: MindPiece | None
    lessons: list
    streams: list[StreamScore]
    filed: list[Path]
    sources_ok: int
    sources_total: int
    sources_failed: list[dict]
    notes: list[str]
    scored_by: str


def run_daily(
    cfg: Config,
    d: date | None = None,
    *,
    mode: str = "daily",
    use_llm: bool = True,
    dry_run: bool = False,
    write_inbox: bool = True,
    usage: UsageStore | None = None,
    seen: SeenStore | None = None,
    plog: PrincipleLog | None = None,
    cstate: CurriculumState | None = None,
) -> DailyResult:
    d = d or today()
    owns_state = usage is None
    rebuilding = (cfg.daily_dir / f"{d}.md").exists()
    usage = usage or UsageStore.load(cfg.data_dir, cfg.get("budget", {}))
    seen = seen or SeenStore.load(cfg.data_dir)
    plog = plog or PrincipleLog.load(cfg.data_dir)
    if owns_state and rebuilding:
        # Same reason as backfill --overwrite: a rebuild must reproduce the day,
        # not pick over what the first run left behind.
        seen.forget_since(d)
        plog.forget_since(d)
    notes: list[str] = []

    # --- collect ---
    backfill = mode == "backfill"
    log.info("collecting for %s%s", d, " (backfill)" if backfill else "")
    results = collect_all(cfg, for_date=d if backfill else None, backfill_only=backfill)
    failed = [
        {"name": r.source.name, "id": r.source.id, "reason": r.error or r.skipped}
        for r in results if not r.ok
    ]
    ok = [r for r in results if r.ok]
    stale = [r for r in ok if r.stale]
    if stale:
        notes.append(
            "Stale feeds (newest item months old, still enabled): "
            + ", ".join(f"{r.source.name} ({r.stale_days}d)" for r in stale[:4]) + "."
        )
    raw = dedupe([i for r in ok for i in r.items])
    if not backfill:
        raw = within_lookback(raw, cfg, reference=d)

    if backfill:
        skipped_live = [s.name for s in cfg.enabled_sources() if not s.backfill]
        if skipped_live:
            notes.append(
                f"Backfill skipped {len(skipped_live)} live-only source"
                f"{'' if len(skipped_live) == 1 else 's'} that cannot return past dates "
                f"({', '.join(skipped_live)})."
            )

    # --- classify + dedupe against history ---
    items = classify_all(raw)
    fresh = [i for i in items if not seen.has(i.key)]
    if len(items) != len(fresh):
        log.info("  %d already seen in an earlier brief", len(items) - len(fresh))

    cap = int(cfg.get("select.max_candidates_per_section", 8))
    mind_pool = prefilter(fresh, "mind", cap)
    stream_pool = prefilter(fresh, "streams", cap)
    log.info("  candidates: %d mind, %d streams (from %d fresh)", len(mind_pool), len(stream_pool), len(fresh))

    # --- score ---
    scorer = build_scorer(cfg, usage, use_llm=use_llm)

    # --- lessons: the curriculum spine, cached so a rebuild costs nothing ---
    syllabus = load_syllabus(cfg.root / cfg.get("curriculum.syllabus", "curriculum/syllabus.yaml"))
    cstate = cstate if cstate is not None else CurriculumState.load(cfg.data_dir)
    if owns_state and rebuilding:
        cstate.forget_since(d)
    topics = next_topics(syllabus, cstate, d, int(cfg.get("curriculum.lessons_per_day", 2)))
    lessons = [get_or_write_lesson(cfg.root, topic, scorer) for topic in topics]
    if topics and not any(l for l in lessons if not l.is_placeholder):
        notes.append("Lessons could not be written this run; the syllabus entries are shown instead.")
    if syllabus.tracks and not topics:
        notes.append("The syllabus is complete — every topic has been taught. Add more to curriculum/syllabus.yaml.")

    mind: MindPiece | None = None
    if mind_pool:
        mind = scorer.summarise_mind(mind_pool[0])
    extra_reading = mind_pool[1 : 1 + int(cfg.get("select.mind_extra_links", 3))]

    scored: list[StreamScore] = scorer.score_streams(stream_pool) if stream_pool else []
    scored.sort(key=lambda s: s.total, reverse=True)
    # Releases the CLI backend's temp config; a no-op for the others.
    getattr(scorer, "close", lambda: None)()

    min_score = float(cfg.get("select.min_stream_score", 4.5))
    picks = [s for s in scored if s.total >= min_score][: int(cfg.get("select.stream_picks", 3))]

    degraded = getattr(scorer, "degraded", [])
    if degraded:
        notes.append("Scoring degraded to the offline scorer for some items (" + "; ".join(sorted(set(degraded))[:2]) + ").")

    # --- save ---
    filed: list[Path] = []
    stream = load_stream(cfg.active_stream_file)
    principles = parse_principles(cfg.principles_file)
    principle = pick_principle(principles, plog, d, int(cfg.get("principles.cooldown_days", 21)))

    cost = f"${usage.cost_usd:.4f}" if usage.calls else ""
    text = compose_daily(
        cfg, d, mind, picks, principle, stream,
        mode=mode, lessons=lessons, extra_reading=extra_reading,
        sources_ok=len(ok), sources_total=len(results), sources_failed=failed,
        notes=notes, scored_by=getattr(scorer, "name", "heuristic"), cost=cost,
        filed=0,
    )

    path = None
    if not dry_run:
        if write_inbox and scored:
            filed = save_ideas(cfg.inbox_dir, scored, captured=d)
        # Re-render so the "filed to inbox" count is accurate.
        text = compose_daily(
            cfg, d, mind, picks, principle, stream,
            mode=mode, lessons=lessons, extra_reading=extra_reading,
            sources_ok=len(ok), sources_total=len(results), sources_failed=failed,
            notes=notes, scored_by=getattr(scorer, "name", "heuristic"), cost=cost,
            filed=len(filed),
        )
        path = write_text(cfg.daily_dir / f"{d}.md", text)

        for item in mind_pool[:1] + stream_pool:
            seen.add(item.key, source=item.source_id, title=item.title, first_seen=d)
        if principle:
            plog.mark(principle.id, d)
        for topic in topics:
            cstate.mark(topic.id, d)
        if owns_state:
            seen.save()
            plog.save()
            cstate.save()
            usage.save(f"daily:{d}", {"mode": mode, "items": len(fresh), "picks": len(picks)})
        # The river: a flat, append-only record of everything surfaced, so the
        # dashboard can show one continuous scroll instead of only day-sized pages.
        river = []
        for lesson in lessons:
            if lesson.is_placeholder:
                continue
            river.append({
                "date": str(d), "kind": "lesson", "track": lesson.topic.track,
                "track_name": lesson.topic.track_name, "id": lesson.topic.id,
                "title": lesson.topic.title, "url": "",
                "snippet": lesson.key_idea, "source": "Syllabus",
            })
        if mind:
            river.append({
                "date": str(d), "kind": "read", "track": getattr(mind.item, "track", ""),
                "track_name": "", "id": mind.item.key, "title": mind.item.title,
                "url": mind.item.url, "snippet": mind.key_idea,
                "source": mind.item.source_name,
                "media": mind.item.extra.get("kind", "read"),
                "duration": mind.item.extra.get("duration", ""),
            })
        for item in extra_reading:
            river.append({
                "date": str(d), "kind": "link", "track": getattr(item, "track", ""),
                "track_name": "", "id": item.key, "title": item.title,
                "url": item.url, "snippet": "", "source": item.source_name,
                "media": item.extra.get("kind", "read"),
                "duration": item.extra.get("duration", ""),
            })
        existing = {r.get("id") for r in read_jsonl(cfg.data_dir / "river.jsonl")
                    if str(r.get("date")) == str(d)}
        for entry in river:
            if entry["id"] not in existing:
                append_jsonl(cfg.data_dir / "river.jsonl", entry)

        log_run(cfg.data_dir, {
            "at": str(d), "mode": mode, "sources_ok": len(ok), "sources_total": len(results),
            "failed": [f["id"] for f in failed], "candidates": len(fresh), "picks": len(picks),
            "scored_by": getattr(scorer, "name", "heuristic"), "cost_usd": round(usage.cost_usd, 5),
        })

    return DailyResult(
        date=d, path=path, text=text, mind=mind, lessons=lessons, streams=picks, filed=filed,
        sources_ok=len(ok), sources_total=len(results), sources_failed=failed,
        notes=notes, scored_by=getattr(scorer, "name", "heuristic"),
    )


def run_weekly(cfg: Config, end: date | None = None, dry_run: bool = False) -> Path | None:
    end = end or today()
    # A digest covers the ISO week containing `end`, Monday..Sunday.
    start, sunday = week_bounds(end)
    briefs = load_week_briefs(cfg, start, min(end, sunday))
    stream = load_stream(cfg.active_stream_file)
    top = load_inbox(cfg, limit=5)
    text = compose_weekly(cfg, min(end, sunday), stream, briefs, top)
    if dry_run:
        print(text)
        return None
    path = write_text(cfg.digest_dir / f"{iso_week(end)}.md", text)
    log.info("wrote %s", path)
    return path


def run_backfill(
    cfg: Config, days: int = 7, end: date | None = None, *, use_llm: bool = True, dry_run: bool = False,
    overwrite: bool = False,
) -> list[DailyResult]:
    """Rebuild the last N days, oldest first.

    Oldest-first matters: dedupe and the principle rotation then replay in the
    order the days actually happened, so the backfilled week reads like a week
    rather than seven copies of today.
    """
    end = end or today()
    start = end - timedelta(days=days - 1)
    usage = UsageStore.load(cfg.data_dir, cfg.get("budget", {}))
    usage.max_usd = float(cfg.get("budget.max_usd_per_backfill", 2.0))
    usage.max_calls = int(cfg.get("budget.max_calls_per_backfill", 90))
    usage.max_input *= days
    usage.max_output *= days
    seen = SeenStore.load(cfg.data_dir)
    plog = PrincipleLog.load(cfg.data_dir)
    cstate = CurriculumState.load(cfg.data_dir)
    if overwrite:
        dropped = seen.forget_since(start)
        plog.forget_since(start)
        cstate.forget_since(start)
        if dropped:
            log.info("forgetting %d item(s) first seen on or after %s so the rebuild is clean", dropped, start)

    out: list[DailyResult] = []
    for d in daterange(start, end):
        target = cfg.daily_dir / f"{d}.md"
        if target.exists() and not overwrite:
            log.info("%s already exists — skipping (use --overwrite to rebuild)", target.name)
            continue
        out.append(run_daily(
            cfg, d, mode="backfill", use_llm=use_llm, dry_run=dry_run,
            usage=usage, seen=seen, plog=plog, cstate=cstate,
        ))
    if not dry_run:
        seen.save()
        plog.save()
        cstate.save()
        usage.save(f"backfill:{start}..{end}", {"days": len(out)})
    return out


# --- CLI --------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lumina", description="Lumina Daily pipeline")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--root", default=str(ROOT), help="repo root (for tests)")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("daily", help="build today's brief")
    d.add_argument("--date", help="YYYY-MM-DD (default: today, JST)")
    d.add_argument("--dry-run", action="store_true", help="print the brief, write nothing")
    d.add_argument("--no-llm", action="store_true", help="use the offline scorer, no API calls")
    d.add_argument("--notify", help="override the notifier: none|slack|email")

    w = sub.add_parser("weekly", help="build the weekly digest")
    w.add_argument("--date", help="any date in the target week (default: today)")
    w.add_argument("--dry-run", action="store_true")

    b = sub.add_parser("backfill", help="rebuild the last N days")
    b.add_argument("--days", type=int, default=7)
    b.add_argument("--end", help="last day to build (default: today)")
    b.add_argument("--dry-run", action="store_true")
    b.add_argument("--no-llm", action="store_true")
    b.add_argument("--overwrite", action="store_true", help="rebuild days that already have a brief")
    b.add_argument("--weekly", action="store_true", help="also rebuild the digests those days fall in")

    c = sub.add_parser("collect", help="collect only, print a source report")
    c.add_argument("--date", help="YYYY-MM-DD for a backfill-style window")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    cfg = load_config(args.root)

    if args.command == "collect":
        from .util import parse_date
        d = parse_date(getattr(args, "date", None))
        results = collect_all(cfg, for_date=d, backfill_only=bool(d))
        total = 0
        print(f"\n{'source':<26} {'items':>6}  status")
        print("-" * 58)
        for r in results:
            total += len(r.items)
            print(f"{r.source.id:<26} {len(r.items):>6}  {'ok' if r.ok else (r.error or r.skipped)}")
        print("-" * 58)
        print(f"{'total':<26} {total:>6}")
        for s in cfg.disabled_sources():
            print(f"\ndisabled: {s.id} — {' '.join((s.disabled_reason or '').split())[:150]}")
        return 0

    if args.command == "daily":
        from .util import parse_date
        res = run_daily(cfg, parse_date(args.date), use_llm=not args.no_llm, dry_run=args.dry_run)
        if args.dry_run:
            print(res.text)
        else:
            log.info("wrote %s", res.path)
            from .notify import notify
            notify(cfg, res, override=args.notify)
        return 0

    if args.command == "weekly":
        from .util import parse_date
        run_weekly(cfg, parse_date(args.date), dry_run=args.dry_run)
        return 0

    if args.command == "backfill":
        from .util import parse_date
        results = run_backfill(
            cfg, days=args.days, end=parse_date(args.end),
            use_llm=not args.no_llm, dry_run=args.dry_run, overwrite=args.overwrite,
        )
        log.info("backfilled %d day(s)", len(results))
        if args.weekly and results and not args.dry_run:
            weeks = sorted({week_bounds(r.date)[1] for r in results})
            for sunday in weeks:
                run_weekly(cfg, sunday)
        return 0

    return 1
