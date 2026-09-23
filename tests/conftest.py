import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lumina.config import load_config  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return load_config(ROOT)


@pytest.fixture
def tmp_cfg(tmp_path, cfg):
    """A config rooted in a temp dir, so tests never touch the real repo."""
    import shutil

    for sub in ("config", "templates", "curriculum"):
        shutil.copytree(cfg.root / sub, tmp_path / sub)
    for sub in ("daily", "digests", "ideas/inbox", "data", "streams/archive"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return load_config(tmp_path)


@pytest.fixture
def sample_feed_bytes():
    return (Path(__file__).parent / "fixtures" / "sample_feed.xml").read_bytes()
