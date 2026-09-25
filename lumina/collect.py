"""Collectors.

Contract every collector honours:
  * it returns (items, error_or_None) and NEVER raises out of collect_all();
  * a source that fails is skipped, recorded, and surfaced in the brief's
    "Run notes" — the run itself always completes;
  * it stores title, link, timestamp and a short excerpt only. The excerpt is
    capped at EXCERPT_WORDS and exists to be scored, not to be a substitute for
    reading the article.
"""

from __future__ import annotations

import os
import re
import time as _time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from typing import Iterable

import feedparser
import httpx

from .config import Config, Source
from .state import item_key
from .util import JST, clip_words, day_bounds, log, strip_html, to_jst

# Copyright guard: never hold more than this much of someone else's prose.
EXCERPT_WORDS = 60

# A feed whose newest item is older than this is reported as stale. Some good
# sources genuinely publish quarterly, so this flags rather than disables.
STALE_AFTER_DAYS = 180


@dataclass
class Item:
    key: str
    title: str
    url: str
    source_id: str
    source_name: str
    section: str
    published: datetime | None = None
    excerpt: str = ""
    author: str = ""
    points: int = 0
    comments: int = 0
    weight: float = 1.0
    track: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def published_jst(self) -> datetime | None:
        return to_jst(self.published) if self.published else None

    @property
    def published_date(self) -> date | None:
        pj = self.published_jst
        return pj.date() if pj else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.isoformat() if self.published else None
        return d


@dataclass
class SourceResult:
    source: Source
    items: list[Item] = field(default_factory=list)
    error: str | None = None
    skipped: str | None = None
    stale_days: int | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.skipped is None

    @property
    def stale(self) -> bool:
        return self.stale_days is not None


# --- http -------------------------------------------------------------------


def _client(cfg: Config, src: Source | None = None) -> httpx.Client:
    headers = {
        "User-Agent": cfg.get("collect.user_agent", "lumina-wealth/1.0"),
        "Accept": "application/rss+xml, application/atom+xml, application/xml, application/json;q=0.9, */*;q=0.8",
    }
    if src and src.headers:
        headers.update(src.headers)
    return httpx.Client(
        timeout=float(cfg.get("collect.timeout_seconds", 20)),
        follow_redirects=True,
        headers=headers,
    )


def _fetch(client: httpx.Client, url: str, cfg: Config, **kwargs) -> httpx.Response:
    """GET with bounded retries. 429/5xx back off; 4xx fails fast (retrying a
    404 just wastes the run's time budget)."""
    retries = int(cfg.get("collect.retries", 2))
    backoff = float(cfg.get("collect.retry_backoff_seconds", 3))
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = client.get(url, **kwargs)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            last = exc
            code = exc.response.status_code if exc.response is not None else 0
            if code and code not in (429, 500, 502, 503, 504):
                raise
            if attempt < retries:
                _time.sleep(backoff * (attempt + 1))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
            if attempt < retries:
                _time.sleep(backoff * (attempt + 1))
    raise last if last else RuntimeError("fetch failed")


_DUR = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")


def _entry_url(entry, feed_link: str = "") -> str:
    """Resolve a usable link.

    Podcast feeds frequently carry no per-episode <link> — the episode lives in
    the <enclosure> and the guid is an internal id like
    `gid://art19-episode-locator/...`. Falling back to the enclosure gives a
    link that both plays and is unique enough to dedupe on.
    """
    link = (getattr(entry, "link", "") or "").strip()
    if link:
        return link
    for enc in (getattr(entry, "enclosures", None) or []):
        href = (enc.get("href") or "").strip()
        if href:
            return href
    for l in (getattr(entry, "links", None) or []):
        href = (l.get("href") or "").strip()
        if href:
            return href
    return feed_link or ""


def _duration(entry) -> tuple[str, str]:
    """(kind, human duration). Podcast feeds carry itunes:duration as either
    seconds or h:mm:ss; articles carry nothing."""
    raw = str(getattr(entry, "itunes_duration", "") or "").strip()
    if not raw:
        return "read", ""
    seconds = None
    if raw.isdigit():
        seconds = int(raw)
    else:
        m = _DUR.match(raw)
        if m:
            h, mm, ss = m.group(1) or 0, m.group(2), m.group(3)
            seconds = int(h) * 3600 + int(mm) * 60 + int(ss)
    if seconds is None:
        return "listen", raw
    if seconds >= 3600:
        return "listen", f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"
    return "listen", f"{max(1, round(seconds / 60))} min"


def _entry_datetime(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


# --- collectors -------------------------------------------------------------


def collect_rss(src: Source, cfg: Config, window: tuple[datetime, datetime] | None) -> list[Item]:
    with _client(cfg, src) as client:
        resp = _fetch(client, src.url, cfg)
        parsed = feedparser.parse(resp.content)
        # bozo just means "not strictly well-formed"; most real feeds trip it and
        # still parse fine, so only an empty result is actually a failure.
        if parsed.bozo and not parsed.entries:
            # A truncated or momentarily corrupt response parses to nothing and
            # is fine seconds later. Re-fetch once before calling it broken.
            log.debug("  %-24s unparseable, re-fetching once", src.id)
            _time.sleep(1.5)
            resp = _fetch(client, src.url, cfg)
            parsed = feedparser.parse(resp.content)
            if parsed.bozo and not parsed.entries:
                raise RuntimeError(f"unparseable feed ({getattr(parsed, 'bozo_exception', 'unknown')})")

    feed_link = (getattr(parsed.feed, "link", "") or "").strip()
    limit = int(cfg.get("collect.max_items_per_source", 40))
    items: list[Item] = []
    # Cap AFTER filtering, not before: the first 40 entries of a podcast feed
    # can all lack a <link>, which silently produced an empty source.
    for entry in parsed.entries:
        if len(items) >= limit:
            break
        url = _entry_url(entry, feed_link)
        title = strip_html(getattr(entry, "title", "")).strip()
        if not url or not title:
            continue
        published = _entry_datetime(entry)
        if window and published and not (window[0] <= published < window[1]):
            continue
        if window and not published:
            # Undated entry in a dated query: cannot place it, so leave it out
            # rather than misattribute it to the day being built.
            continue
        summary = getattr(entry, "summary", "") or ""
        if not summary and getattr(entry, "content", None):
            summary = entry.content[0].get("value", "")
        kind, duration = _duration(entry)
        items.append(
            Item(
                key=item_key(url, title),
                title=title,
                url=url,
                source_id=src.id,
                source_name=src.name,
                section=src.section,
                published=published,
                excerpt=clip_words(summary, EXCERPT_WORDS),
                author=strip_html(getattr(entry, "author", "")) or "",
                weight=src.weight,
                track=src.track,
                extra={"kind": kind, "duration": duration, "media": src.media},
            )
        )
    return items


def collect_hn_algolia(src: Source, cfg: Config, window: tuple[datetime, datetime] | None) -> list[Item]:
    """Hacker News via the public Algolia API.

    The only source here that supports a real historical date range
    (created_at_i numeric filters), which is what makes backfill honest.
    """
    params = {
        "tags": src.params.get("tags", "show_hn"),
        "hitsPerPage": min(int(cfg.get("collect.max_items_per_source", 40)) * 2, 100),
    }
    numeric = []
    if window:
        numeric.append(f"created_at_i>{int(window[0].timestamp())}")
        numeric.append(f"created_at_i<{int(window[1].timestamp())}")
    min_points = int(src.params.get("min_points", 0) or 0)
    if min_points:
        numeric.append(f"points>={min_points}")
    if numeric:
        params["numericFilters"] = ",".join(numeric)

    with _client(cfg) as client:
        resp = _fetch(client, src.url, cfg, params=params)
    payload = resp.json()

    items: list[Item] = []
    for hit in payload.get("hits", []):
        title = strip_html(hit.get("title") or hit.get("story_title") or "").strip()
        if not title:
            continue
        object_id = hit.get("objectID")
        discussion = f"https://news.ycombinator.com/item?id={object_id}"
        url = (hit.get("url") or "").strip() or discussion
        created = hit.get("created_at_i")
        published = datetime.fromtimestamp(created, tz=timezone.utc) if created else None
        items.append(
            Item(
                key=item_key(url, title),
                title=title,
                url=url,
                source_id=src.id,
                source_name=src.name,
                section=src.section,
                published=published,
                excerpt=clip_words(hit.get("story_text") or hit.get("comment_text") or "", EXCERPT_WORDS),
                author=hit.get("author") or "",
                points=int(hit.get("points") or 0),
                comments=int(hit.get("num_comments") or 0),
                weight=src.weight,
                extra={"discussion_url": discussion},
            )
        )
    return items


class _RedditConfig:
    """Wraps Config with a longer backoff, for Reddit only.

    Everything else should fail fast; Reddit is the one source where waiting
    actually changes the outcome.
    """

    def __init__(self, cfg: Config):
        self._cfg = cfg

    def get(self, dotted: str, default=None):
        overrides = {"collect.retry_backoff_seconds": 20, "collect.retries": 2}
        if dotted in overrides:
            return overrides[dotted]
        return self._cfg.get(dotted, default)

    def __getattr__(self, name):
        return getattr(self._cfg, name)


def collect_reddit_rss(src: Source, cfg: Config, window: tuple[datetime, datetime] | None) -> list[Item]:
    """Reddit public .rss.

    No auth needed and within the public-content terms, but /new reaches back
    only a couple of hours and Reddit rate-limits datacenter IPs aggressively
    (429s are normal from CI). Both facts are handled by the caller: it is a
    skip, not a failure. Backfill never calls this — sources.yaml marks it
    backfill: false.
    """
    if os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET"):
        log.debug("reddit credentials present but the OAuth path is not enabled; using public rss")
    # Reddit's unauthenticated limit needs far longer than a generic 429 backoff;
    # 3s then 6s never cleared it. Give this source its own, patient settings.
    patient = _RedditConfig(cfg)
    items = collect_rss(src, patient, window)
    for it in items:
        it.extra.setdefault("subreddit", src.name)
    return items


def collect_producthunt(src: Source, cfg: Config, window: tuple[datetime, datetime] | None) -> list[Item]:
    """Product Hunt public Atom feed (~1 day of posts, no auth).

    PRODUCTHUNT_TOKEN would unlock the GraphQL v2 API and with it real date
    ranges; until that token exists this stays feed-only, which is why
    sources.yaml marks it backfill: false.
    """
    if os.getenv("PRODUCTHUNT_TOKEN"):
        log.debug("PRODUCTHUNT_TOKEN present; graphql path not implemented, using public feed")
    return collect_rss(src, cfg, window)


COLLECTORS = {
    "rss": collect_rss,
    "hn_algolia": collect_hn_algolia,
    "reddit_rss": collect_reddit_rss,
    "producthunt_rss": collect_producthunt,
}


# --- orchestration ----------------------------------------------------------


def collect_source(
    src: Source, cfg: Config, window: tuple[datetime, datetime] | None = None
) -> SourceResult:
    collector = COLLECTORS.get(src.kind)
    if collector is None:
        return SourceResult(source=src, skipped=f"unknown collector kind '{src.kind}'")
    try:
        items = collector(src, cfg, window)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        note = "rate limited" if code == 429 else f"HTTP {code}"
        return SourceResult(source=src, error=note)
    except Exception as exc:  # deliberately broad: one bad source never ends a run
        return SourceResult(source=src, error=f"{type(exc).__name__}: {exc}"[:180])
    # A feed can return HTTP 200, parse cleanly, and still be abandoned — Get
    # Rich Slowly answered 200 with a newest post from December 2022. Report
    # age so a dead source is visible rather than silently contributing nothing.
    stale_days = None
    dated = [i.published for i in items if i.published]
    if dated:
        age = (datetime.now(timezone.utc) - max(dated)).days
        if age > STALE_AFTER_DAYS:
            stale_days = age
            log.warning("  %-24s newest item is %d days old — treating as stale", src.id, age)
    elif items:
        log.debug("  %-24s items carry no dates; cannot judge freshness", src.id)

    log.info("  %-24s %3d items", src.id, len(items))
    return SourceResult(source=src, items=items, stale_days=stale_days)


def collect_all(
    cfg: Config,
    section: str | None = None,
    for_date: date | None = None,
    backfill_only: bool = False,
) -> list[SourceResult]:
    """Collect every enabled source.

    for_date restricts to that JST calendar day (used by backfill); otherwise
    the window is the last `collect.lookback_days`.
    """
    window: tuple[datetime, datetime] | None = None
    if for_date is not None:
        window = day_bounds(for_date)

    sources = cfg.backfill_sources(section) if backfill_only else cfg.enabled_sources(section)
    results: list[SourceResult] = []
    for src in sources:
        results.append(collect_source(src, cfg, window))
    return results


def dedupe(items: Iterable[Item]) -> list[Item]:
    """Collapse the same story arriving from two sources, keeping the first."""
    out: dict[str, Item] = {}
    for it in items:
        if it.key not in out:
            out[it.key] = it
    return list(out.values())


def within_lookback(items: Iterable[Item], cfg: Config, reference: date | None = None) -> list[Item]:
    """Drop items older than collect.lookback_days relative to `reference`."""
    from datetime import timedelta

    reference = reference or datetime.now(JST).date()
    cutoff = reference - timedelta(days=int(cfg.get("collect.lookback_days", 3)))
    kept = []
    for it in items:
        pd = it.published_date
        if pd is None or (cutoff <= pd <= reference):
            kept.append(it)
    return kept
