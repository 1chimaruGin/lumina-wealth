from datetime import date, datetime, timezone

import pytest

from lumina import collect
from lumina.collect import Item, dedupe, within_lookback
from lumina.config import Source
from lumina.state import canonical_url, item_key


@pytest.fixture
def rss_source():
    return Source(id="sample", name="Sample", kind="rss", url="https://example.com/feed",
                  section="mind", enabled=True, backfill=True)


def _patch_fetch(monkeypatch, body: bytes):
    class FakeResponse:
        content = body

        def json(self):
            raise AssertionError("not json")

    monkeypatch.setattr(collect, "_fetch", lambda *a, **k: FakeResponse())
    monkeypatch.setattr(collect, "_client", lambda cfg: _NullCtx())


class _NullCtx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_rss_parses_and_normalises(cfg, rss_source, sample_feed_bytes, monkeypatch):
    _patch_fetch(monkeypatch, sample_feed_bytes)
    items = collect.collect_rss(rss_source, cfg, None)
    assert len(items) == 3
    first = items[0]
    assert first.title == "The lifestyle creep nobody notices"
    assert first.published_date == date(2026, 9, 21)
    assert "<p>" not in first.excerpt  # html stripped


def test_excerpt_is_capped_for_copyright(cfg, rss_source, sample_feed_bytes, monkeypatch):
    _patch_fetch(monkeypatch, sample_feed_bytes)
    for item in collect.collect_rss(rss_source, cfg, None):
        assert len(item.excerpt.split()) <= collect.EXCERPT_WORDS


def test_date_window_filters_and_drops_undated(cfg, rss_source, sample_feed_bytes, monkeypatch):
    _patch_fetch(monkeypatch, sample_feed_bytes)
    window = (datetime(2026, 9, 21, tzinfo=timezone.utc), datetime(2026, 9, 22, tzinfo=timezone.utc))
    items = collect.collect_rss(rss_source, cfg, window)
    # Only the 21st. The undated item is dropped rather than misattributed.
    assert [i.published_date for i in items] == [date(2026, 9, 21)]


def test_failing_source_is_skipped_not_raised(cfg, rss_source, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("feed exploded")

    # Patch the registry, not the module attribute: COLLECTORS captured the
    # original function at import time.
    monkeypatch.setitem(collect.COLLECTORS, "rss", boom)
    result = collect.collect_source(rss_source, cfg, None)
    assert not result.ok
    assert "feed exploded" in result.error
    assert result.items == []


def test_unknown_kind_is_skipped(cfg):
    src = Source(id="x", name="X", kind="carrier-pigeon", url="", section="mind")
    result = collect.collect_source(src, cfg, None)
    assert result.skipped and "carrier-pigeon" in result.skipped


def test_canonical_url_strips_tracking_and_case():
    a = canonical_url("HTTPS://www.Example.com/post/?utm_source=x&id=3")
    b = canonical_url("https://example.com/post?id=3")
    assert a == b
    assert item_key(a) == item_key(b)


def _item(url, title="t", when=None):
    return Item(key=item_key(url, title), title=title, url=url, source_id="s",
                source_name="S", section="streams", published=when)


def test_dedupe_keeps_first():
    dupes = [_item("https://example.com/a"), _item("https://www.example.com/a/")]
    assert len(dedupe(dupes)) == 1


def test_within_lookback_keeps_undated(cfg):
    old = _item("https://example.com/old", when=datetime(2020, 1, 1, tzinfo=timezone.utc))
    recent = _item("https://example.com/new", when=datetime(2026, 9, 23, tzinfo=timezone.utc))
    undated = _item("https://example.com/undated")
    kept = within_lookback([old, recent, undated], cfg, reference=date(2026, 9, 23))
    urls = {i.url for i in kept}
    assert "https://example.com/old" not in urls
    assert "https://example.com/new" in urls and "https://example.com/undated" in urls
