#!/usr/bin/env python3
"""Score today's candidates without writing anything. A dry daily run."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lumina.run import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["daily", "--dry-run", *sys.argv[1:]]))
