#!/usr/bin/env python3
"""Build the daily brief. `python scripts/compose.py --date 2026-09-23 --dry-run`"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lumina.run import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["daily", *sys.argv[1:]]))
