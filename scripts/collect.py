#!/usr/bin/env python3
"""Collect only, and print a per-source report. `python scripts/collect.py --help`"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lumina.run import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["collect", *sys.argv[1:]]))
