#!/usr/bin/env python3
"""Rebuild the last N days. `python scripts/backfill.py --days 7`"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lumina.run import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["backfill", *sys.argv[1:]]))
