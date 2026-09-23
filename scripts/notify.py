#!/usr/bin/env python3
"""Send the most recent brief through the configured notifier.

Useful for testing a webhook without regenerating a brief:
    python scripts/notify.py --channel slack
"""
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lumina.config import load_config  # noqa: E402
from lumina.notify import notify  # noqa: E402
from lumina.util import setup_logging  # noqa: E402


@dataclass
class _Brief:
    date: str
    text: str
    streams: list
    mind: None = None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--channel", help="none|slack|email (default: config/settings.yaml)")
    ap.add_argument("--date", help="which brief to send (default: the newest)")
    args = ap.parse_args()
    setup_logging()

    cfg = load_config()
    briefs = sorted(cfg.daily_dir.glob("20*.md"))
    if not briefs:
        print("no briefs in daily/ yet", file=sys.stderr)
        return 1
    path = (cfg.daily_dir / f"{args.date}.md") if args.date else briefs[-1]
    if not path.exists():
        print(f"no brief at {path}", file=sys.stderr)
        return 1
    ok = notify(cfg, _Brief(date=path.stem, text=path.read_text(encoding="utf-8"), streams=[]),
                override=args.channel)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
