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
    monkeypatch.setattr(collect, "_client", lambda cfg, src=None: _NullCtx())


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


def test_podcast_entry_without_a_link_falls_back_to_the_enclosure():
    """Podcast feeds routinely omit per-episode <link>; the episode lives in
    <enclosure> and the guid is an internal id. Requiring <link> silently
    emptied two 800-episode feeds."""
    from lumina.collect import _entry_url

    class Entry:
        link = ""
        enclosures = [{"href": "https://cdn.example.com/ep42.mp3"}]

    assert _entry_url(Entry(), "https://show.example.com") == "https://cdn.example.com/ep42.mp3"


def test_entry_url_prefers_a_real_link():
    from lumina.collect import _entry_url

    class Entry:
        link = "https://example.com/episode-42"
        enclosures = [{"href": "https://cdn.example.com/ep42.mp3"}]

    assert _entry_url(Entry(), "") == "https://example.com/episode-42"


def test_cap_is_applied_after_filtering_not_before(cfg, rss_source, monkeypatch):
    """The first N entries of a podcast feed can all be unusable. Capping first
    turned an 870-episode feed into zero items."""
    entries = "".join(
        f"<item><title>No link {i}</title><pubDate>Mon, 21 Sep 2026 09:00:00 +0000</pubDate></item>"
        for i in range(45)
    ) + "".join(
        f'<item><title>Good {i}</title><link>https://example.com/g{i}</link>'
        f"<pubDate>Mon, 21 Sep 2026 09:00:00 +0000</pubDate></item>"
        for i in range(5)
    )
    feed = f"<?xml version='1.0'?><rss version='2.0'><channel><title>T</title>{entries}</channel></rss>"
    _patch_fetch(monkeypatch, feed.encode())
    items = collect.collect_rss(rss_source, cfg, None)
    assert len(items) == 5
    assert all(i.url.startswith("https://example.com/g") for i in items)


def test_stale_feed_is_reported_but_not_dropped(cfg, rss_source, monkeypatch):
    old = ("<?xml version='1.0'?><rss version='2.0'><channel><title>T</title>"
           "<item><title>Ancient</title><link>https://example.com/a</link>"
           "<pubDate>Fri, 02 Dec 2022 09:00:00 +0000</pubDate></item></channel></rss>")
    _patch_fetch(monkeypatch, old.encode())
    result = collect.collect_source(rss_source, cfg, None)
    assert result.ok                 # still usable, not an error
    assert result.stale              # but flagged
    assert result.stale_days > 365


def test_a_momentarily_unparseable_feed_is_refetched_once(cfg, rss_source, monkeypatch):
    """Tim Harford's feed failed a single run with 'not well-formed (invalid
    token)' and parsed fine seconds later. One bad response should not lose the
    source for the day."""
    good = ("<?xml version='1.0'?><rss version='2.0'><channel><title>T</title>"
            "<item><title>Real</title><link>https://example.com/a</link>"
            "<pubDate>Mon, 21 Sep 2026 09:00:00 +0000</pubDate></item></channel></rss>").encode()
    calls = {"n": 0}

    class R:
        def __init__(self, body): self.content = body

    def fetch(client, url, cfg_, **kw):
        calls["n"] += 1
        return R(b"<rss><chan" if calls["n"] == 1 else good)   # truncated, then fine

    monkeypatch.setattr(collect, "_fetch", fetch)
    monkeypatch.setattr(collect, "_client", lambda cfg_, src=None: _NullCtx())
    monkeypatch.setattr(collect._time, "sleep", lambda s: None)

    items = collect.collect_rss(rss_source, cfg, None)
    assert calls["n"] == 2
    assert [i.title for i in items] == ["Real"]


def test_a_persistently_broken_feed_still_fails(cfg, rss_source, monkeypatch):
    class R:
        content = b"<rss><chan"

    monkeypatch.setattr(collect, "_fetch", lambda *a, **k: R())
    monkeypatch.setattr(collect, "_client", lambda cfg_, src=None: _NullCtx())
    monkeypatch.setattr(collect._time, "sleep", lambda s: None)
    result = collect.collect_source(rss_source, cfg, None)
    assert not result.ok and "unparseable" in result.error


def test_reddit_gets_a_longer_backoff_than_everything_else(cfg):
    """A generic 3s/6s backoff never cleared Reddit's rate limit."""
    from lumina.collect import _RedditConfig

    patient = _RedditConfig(cfg)
    assert patient.get("collect.retry_backoff_seconds") == 20
    assert cfg.get("collect.retry_backoff_seconds") < 20
    # everything else passes through untouched
    assert patient.get("collect.timeout_seconds") == cfg.get("collect.timeout_seconds")


def test_the_builder_subreddits_are_one_request_not_three(cfg):
    reddit = [s for s in cfg.enabled_sources() if s.kind == "reddit_rss"]
    assert len(reddit) <= 2, "each Reddit source is another chance to be rate limited"
    builders = next((s for s in reddit if "SideProject" in s.url), None)
    assert builders and "+" in builders.url        # multireddit form
