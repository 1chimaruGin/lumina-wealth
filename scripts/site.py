#!/usr/bin/env python3
"""Build the dashboard at site/index.html.

    python scripts/site.py            # build
    python scripts/site.py --open     # build, then open it in a browser
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lumina.config import load_config  # noqa: E402
from lumina.site import build_site  # noqa: E402
from lumina.util import log, setup_logging  # noqa: E402


def open_in_browser(path: Path) -> bool:
    """Open the built page. WSL is handled explicitly because a Linux browser
    opener there either is not installed or opens nothing visible."""
    url = path.as_uri()
    is_wsl = "microsoft" in os.uname().release.lower()

    if is_wsl and shutil.which("wslview"):
        cmd = ["wslview", str(path)]
    elif is_wsl and shutil.which("explorer.exe"):
        # explorer.exe wants a Windows path and returns non-zero even on success.
        win = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True)
        subprocess.run(["explorer.exe", win.stdout.strip()], capture_output=True)
        return True
    elif sys.platform == "darwin":
        cmd = ["open", url]
    elif shutil.which("xdg-open"):
        cmd = ["xdg-open", url]
    else:
        return False

    try:
        subprocess.run(cmd, capture_output=True, check=False)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="output path (default: site/index.html)")
    ap.add_argument("--open", action="store_true", help="open the page in a browser")
    ap.add_argument("--fragment", action="store_true",
                    help="emit without the html/head/body wrapper, for a host that supplies one")
    args = ap.parse_args()
    setup_logging()

    path = build_site(load_config(), Path(args.out) if args.out else None, fragment=args.fragment)

    if args.open:
        if args.fragment:
            log.warning("--fragment has no document wrapper; opening it in a browser will look wrong")
        if not open_in_browser(path):
            log.info("no browser opener found — open this yourself:")
        print(path.as_uri())
