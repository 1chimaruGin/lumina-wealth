"""Dashboard data assembly. These cover the two bug classes that broke it:
missing keys under StrictUndefined, and ordering that buried the lessons."""

import json

from lumina.site import build_site, collect_data


def _write_river(cfg, rows):
    path = cfg.data_dir / "river.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_river_entries_are_normalised(tmp_cfg):
    """A lesson row has no duration; a link row has no snippet. Every row must
    still come out with the full key set or the template dies."""
    _write_river(tmp_cfg, [
        {"date": "2026-09-20", "kind": "lesson", "title": "L", "track": "history"},
        {"date": "2026-09-20", "kind": "link", "title": "K", "url": "https://e.com"},
    ])
    data = collect_data(tmp_cfg)
    required = {"date", "kind", "track", "title", "url", "snippet", "source", "media", "duration", "id"}
    for row in data["river"]:
        assert required <= set(row), f"missing: {required - set(row)}"


def test_lessons_lead_each_day_in_the_river(tmp_cfg):
    _write_river(tmp_cfg, [
        {"date": "2026-09-20", "kind": "link", "title": "a link"},
        {"date": "2026-09-20", "kind": "read", "title": "a read"},
        {"date": "2026-09-20", "kind": "lesson", "title": "a lesson"},
    ])
    kinds = [r["kind"] for r in collect_data(tmp_cfg)["river"]]
    assert kinds == ["lesson", "read", "link"]


def test_river_is_newest_day_first(tmp_cfg):
    _write_river(tmp_cfg, [
        {"date": "2026-09-18", "kind": "lesson", "title": "older"},
        {"date": "2026-09-20", "kind": "lesson", "title": "newer"},
    ])
    assert [r["date"] for r in collect_data(tmp_cfg)["river"]] == ["2026-09-20", "2026-09-18"]


def test_track_progress_covers_every_syllabus_track(tmp_cfg):
    data = collect_data(tmp_cfg)
    assert {t["key"] for t in data["tracks"]} == {
        "psychology", "intelligence", "history", "financing", "management"}
    assert data["syllabus_total"] == sum(t["total"] for t in data["tracks"])
    for t in data["tracks"]:
        assert 0 <= t["pct"] <= 100


def test_site_builds_from_an_empty_repo(tmp_cfg):
    """No briefs, no lessons, no river. The page must still render rather than
    failing on an empty collection."""
    out = build_site(tmp_cfg, tmp_cfg.root / "site" / "index.html")
    html = out.read_text(encoding="utf-8")
    assert "<title>" in html
    assert "The slot is open" in html


def test_site_builds_as_a_fragment_without_the_document_wrapper(tmp_cfg):
    out = build_site(tmp_cfg, tmp_cfg.root / "site" / "frag.html", fragment=True)
    html = out.read_text(encoding="utf-8")
    assert "<!doctype html>" not in html.lower()
    assert "<title>" in html
