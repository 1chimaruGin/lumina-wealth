#!/usr/bin/env python3
"""Build the dashboard at site/index.html.

    python scripts/site.py            # build
    python scripts/site.py --open     # build and print a file:// URL
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lumina.config import load_config  # noqa: E402
from lumina.site import build_site  # noqa: E402
from lumina.util import setup_logging  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="output path (default: site/index.html)")
    ap.add_argument("--open", action="store_true", help="print a file:// URL when done")
    ap.add_argument("--fragment", action="store_true", help="emit without the html/head/body wrapper")
    args = ap.parse_args()
    setup_logging()
    path = build_site(load_config(), Path(args.out) if args.out else None, fragment=args.fragment)
    if args.open:
        print(f"file://{path}")
