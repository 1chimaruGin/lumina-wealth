#!/usr/bin/env python3
"""Build the weekly digest. `python scripts/weekly.py --date 2026-09-20`"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lumina.run import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["weekly", *sys.argv[1:]]))
