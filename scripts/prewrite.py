#!/usr/bin/env python3
"""Write lessons ahead of time instead of waiting for the daily drip.

Lessons are normally generated 3 a day and cached, so the library fills over
months. This writes them in bulk — a whole track, or the entire syllabus — so
you can read ahead or browse a subject you care about now.

    python scripts/prewrite.py --track time            # one track
    python scripts/prewrite.py --track time --jobs 4   # faster
    python scripts/prewrite.py --all --limit 50        # a slice of everything
    python scripts/prewrite.py --track time --dry-run  # just list what is missing

Already-written lessons are skipped, so it is safe to re-run and safe to stop
partway. The daily brief picks up whatever exists.
"""
from __future__ import annotations

import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lumina.config import load_config  # noqa: E402
from lumina.curriculum import (  # noqa: E402
    load_lesson, load_syllabus, save_lesson,
)
from lumina.score import build_scorer  # noqa: E402
from lumina.state import UsageStore  # noqa: E402
from lumina.util import log, setup_logging  # noqa: E402

_print_lock = threading.Lock()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--track", help="only this track (e.g. time, investing, markets)")
    ap.add_argument("--all", action="store_true", help="every track")
    ap.add_argument("--limit", type=int, help="stop after this many lessons")
    ap.add_argument("--jobs", type=int, default=3,
                    help="lessons written in parallel (default 3; the model backend "
                         "is the bottleneck, and too many will hit a rate limit)")
    ap.add_argument("--dry-run", action="store_true", help="list what is missing, write nothing")
    args = ap.parse_args()
    setup_logging()

    if not (args.track or args.all):
        ap.error("give --track NAME or --all")

    cfg = load_config()
    syllabus = load_syllabus(cfg.root / cfg.get("curriculum.syllabus", "curriculum/syllabus.yaml"))
    if args.track and args.track not in syllabus.tracks:
        print(f"unknown track {args.track!r}. Available: {', '.join(syllabus.tracks)}", file=sys.stderr)
        return 2

    topics = (syllabus.tracks[args.track].topics if args.track else syllabus.all_topics)
    def needs_writing(topic) -> bool:
        existing = load_lesson(cfg.root, topic)
        return existing is None or existing.is_placeholder

    missing = [t for t in topics if needs_writing(t)]
    if args.limit:
        missing = missing[: args.limit]

    print(f"{len(topics)} topics in scope · {len(missing)} not yet written")
    if args.dry_run or not missing:
        for t in missing[:40]:
            print(f"  {t.track:<13} {t.id}  {t.title}")
        if len(missing) > 40:
            print(f"  … and {len(missing) - 40} more")
        return 0

    # The budget for a bulk run is its own; a per-day ceiling would stop it early.
    usage = UsageStore.load(cfg.data_dir, cfg.get("budget", {}))
    usage.max_calls = len(missing) + 10
    usage.max_input *= max(1, len(missing))
    usage.max_output *= max(1, len(missing))

    done = {"n": 0, "failed": 0}

    def write_one(topic):
        # One scorer per worker: the CLI backend shells out per call, so sharing
        # a single instance across threads buys nothing and complicates cleanup.
        scorer = build_scorer(cfg, usage, use_llm=True)
        try:
            lesson = scorer.write_lesson(topic)
            if lesson.is_placeholder:
                return topic, False
            save_lesson(cfg.root, lesson)
            return topic, True
        finally:
            getattr(scorer, "close", lambda: None)()

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(write_one, t): t for t in missing}
        for fut in as_completed(futures):
            topic = futures[fut]
            try:
                _, ok = fut.result()
            except Exception as exc:
                ok = False
                log.warning("%s failed: %s", topic.id, exc)
            done["n" if ok else "failed"] += 1
            with _print_lock:
                print(f"  [{done['n'] + done['failed']:>3}/{len(missing)}] "
                      f"{'ok  ' if ok else 'FAIL'} {topic.track}/{topic.id}  {topic.title[:52]}")

    usage.save(f"prewrite:{args.track or 'all'}", {"written": done["n"], "failed": done["failed"]})
    print(f"\nwritten {done['n']} · failed {done['failed']} · "
          f"{usage.calls} calls, {(usage.input_tokens + usage.output_tokens) / 1000:.0f}k tokens"
          + ("" if not usage.billed else f" · ${usage.cost_usd:.4f}"))
    return 0 if not done["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
