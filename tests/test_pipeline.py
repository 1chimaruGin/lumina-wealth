"""Classification, selection, principle rotation, composition, inbox writing."""

from datetime import date, datetime, timedelta, timezone

from lumina.classify import classify, classify_all, is_noise, prefilter
from lumina.collect import Item
from lumina.compose import compose_daily, todays_action
from lumina.inbox import render_idea, save_ideas
from lumina.principles import parse_principles, pick_principle
from lumina.score import HeuristicScorer
from lumina.state import PrincipleLog, SeenStore, UsageStore
from lumina.streams import Stream, split_frontmatter

D = date(2026, 9, 23)


def _item(title, section="streams", source_id="hn_show", excerpt="", points=0):
    return Item(key=title, title=title, url=f"https://example.com/{abs(hash(title))}",
                source_id=source_id, source_name="Src", section=section, excerpt=excerpt,
                points=points, published=datetime(2026, 9, 23, tzinfo=timezone.utc))


def test_hn_money_psychology_moves_to_mind():
    it = _item("On patience, loss aversion and the psychology of compounding wealth")
    assert classify(it) == "mind"


def test_hn_launch_stays_in_streams():
    assert classify(_item("Show HN: I built a SaaS doing $4k MRR")) == "streams"


def test_declared_section_is_respected():
    assert classify(_item("A quiet essay", section="mind", source_id="fs")) == "mind"


def test_noise_is_dropped():
    assert is_noise(_item("The best memecoin airdrop strategy"))
    kept = classify_all([_item("Show HN: a CLI"), _item("Crypto airdrop guide")])
    assert len(kept) == 1


def test_prefilter_caps_and_ranks():
    items = [_item(f"Show HN: tool {i} with paying customers and MRR", points=i) for i in range(20)]
    picked = prefilter(classify_all(items), "streams", 8)
    assert len(picked) == 8


def test_heuristic_scorer_is_deterministic(cfg):
    s = HeuristicScorer(cfg)
    items = [_item("Show HN: a Python API consulting retainer with paying clients")]
    assert s.score_streams(items)[0].total == s.score_streams(items)[0].total


def test_heuristic_scores_are_in_range(cfg):
    s = HeuristicScorer(cfg)
    for score in s.score_streams([_item(f"thing {i}") for i in range(5)]):
        assert 1.0 <= score.total <= 10.0
        assert score.rung in {"1-skills", "2-productized", "3-product", "4-assets"}


def test_offline_summary_is_labelled_not_passed_off(cfg):
    piece = HeuristicScorer(cfg).summarise_mind(_item("A post", excerpt="some words here"))
    assert "Offline mode" in piece.summary


def test_principles_parse(cfg):
    ps = parse_principles(cfg.principles_file)
    assert len(ps) >= 20
    assert all(p.id and p.title and p.source for p in ps)
    assert all(p.prompt for p in ps)


def test_principle_rotation_has_no_immediate_repeats(cfg, tmp_path):
    ps = parse_principles(cfg.principles_file)
    plog = PrincipleLog(path=tmp_path / "p.json", shown={})
    seen = []
    for i in range(len(ps)):
        pick = pick_principle(ps, plog, D + timedelta(days=i), cooldown_days=21)
        plog.mark(pick.id, D + timedelta(days=i))
        seen.append(pick.id)
    assert len(set(seen)) == len(ps)  # every principle used before any repeat


def test_principle_pick_is_stable_for_a_date(cfg, tmp_path):
    ps = parse_principles(cfg.principles_file)
    plog = PrincipleLog(path=tmp_path / "p.json", shown={})
    assert pick_principle(ps, plog, D).id == pick_principle(ps, plog, D).id


def test_compose_daily_renders_every_section(cfg):
    scorer = HeuristicScorer(cfg)
    mind = scorer.summarise_mind(_item("A money habit piece", section="mind", excerpt="words"))
    streams = scorer.score_streams([_item("Show HN: a tool")])
    principle = parse_principles(cfg.principles_file)[0]
    text = compose_daily(cfg, D, mind, streams, principle, Stream(),
                         sources_ok=9, sources_total=11, sources_failed=[])
    for heading in ("## 1 · Money school", "## 2 · Today's reading", "## 3 · Opportunities",
                    "## 4 · Principle", "## 5 · Today's action", "## 6 · Stream status"):
        assert heading in text
    meta, _ = split_frontmatter(text)
    assert str(meta["date"]) == "2026-09-23"


def test_compose_survives_an_empty_day(cfg):
    text = compose_daily(cfg, D, None, [], None, Stream(),
                         sources_ok=0, sources_total=11,
                         sources_failed=[{"name": "X", "id": "x", "reason": "rate limited"}])
    assert "## 1 · Money school" in text and "rate limited" in text


def test_failed_sources_are_named_in_the_brief(cfg):
    text = compose_daily(cfg, D, None, [], None, Stream(), sources_ok=8, sources_total=11,
                         sources_failed=[{"name": "r/SaaS", "id": "reddit_saas", "reason": "rate limited"}])
    assert "r/SaaS" in text and "8/11 sources" in text


def test_action_is_stable_per_day_and_rotates(cfg):
    s = Stream(status="active", name="X", rung="1-skills", started=D,
               next_actions=["a", "b", "c"])
    assert todays_action(s, D) == todays_action(s, D)
    week = {todays_action(s, D + timedelta(days=i)) for i in range(3)}
    assert week == {"a", "b", "c"}


def test_inbox_frontmatter_is_valid_and_unactivated(cfg, tmp_path):
    score = HeuristicScorer(cfg).score_streams([_item("Show HN: a thing")])[0]
    written = save_ideas(tmp_path, [score], captured=D)
    assert len(written) == 1
    meta, body = split_frontmatter(written[0].read_text())
    assert meta["status"] == "inbox"          # nothing auto-activates
    assert meta["rung"] in {"1-skills", "2-productized", "3-product", "4-assets"}
    assert 1 <= meta["score"] <= 10
    assert str(meta["captured"]) == "2026-09-23"


def test_inbox_does_not_overwrite_triaged_ideas(cfg, tmp_path):
    score = HeuristicScorer(cfg).score_streams([_item("Show HN: a thing")])[0]
    path = save_ideas(tmp_path, [score], captured=D)[0]
    path.write_text(path.read_text().replace("status: inbox", "status: rejected"))
    assert save_ideas(tmp_path, [score], captured=D) == []
    assert "status: rejected" in path.read_text()


def test_seen_store_dedupes_across_runs(tmp_path):
    store = SeenStore.load(tmp_path)
    store.add("k1", source="s", title="t", first_seen=D)
    store.save()
    assert SeenStore.load(tmp_path).has("k1")


def test_budget_stops_rather_than_raising(tmp_path):
    usage = UsageStore.load(tmp_path, {"max_usd_per_run": 0.001, "price_per_mtok_input": 1.0,
                                       "price_per_mtok_output": 5.0})
    assert usage.exhausted() is None
    usage.record(2000, 2000)
    assert "cost ceiling" in usage.exhausted()


def test_shorten_never_cuts_mid_word():
    from lumina.util import shorten
    text = "Build and sell pre-built AI agent skills for specific business automation tasks"
    out = shorten(text, 64)
    assert len(out) <= 64
    assert text.startswith(out)          # a real prefix, not a mangled one
    assert not out.endswith(" ")
    assert text[len(out)] == " "         # the cut landed on a word boundary


def test_shorten_leaves_short_text_alone():
    from lumina.util import shorten
    assert shorten("already short", 64) == "already short"


def test_inbox_exposes_the_opportunity_not_just_the_headline(cfg, tmp_path):
    """The dashboard offers the top idea as a stream name. It must offer the
    thing you would sell, not the Hacker News headline it came from."""
    from lumina.inbox import save_ideas
    from lumina.site import collect_data
    from lumina.score import HeuristicScorer

    score = HeuristicScorer(cfg).score_streams([_item("Show HN: some launch post")])[0]
    score.opportunity = "Postgres performance audits for agencies"
    save_ideas(tmp_cfg_inbox := (tmp_path / "inbox"), [score], captured=D)
    meta, body = split_frontmatter(next(tmp_cfg_inbox.glob("*.md")).read_text())
    assert "**Opportunity:** Postgres performance audits for agencies" in body
    assert meta["title"] == "Show HN: some launch post"


def test_brief_renders_for_items_without_duration_metadata(cfg):
    """HN items carry an `extra` dict with no duration key. Accessing it as an
    attribute under StrictUndefined would crash the whole run."""
    scorer = HeuristicScorer(cfg)
    item = _item("An HN post", section="mind")
    item.extra = {"discussion_url": "https://news.ycombinator.com/item?id=1"}
    mind = scorer.summarise_mind(item)
    text = compose_daily(cfg, D, mind, [], None, Stream(), extra_reading=[item],
                         sources_ok=1, sources_total=1, sources_failed=[])
    assert "An HN post" in text


def test_podcast_duration_is_parsed_from_itunes_tags():
    from lumina.collect import _duration

    class E:
        itunes_duration = "1:23:45"
    assert _duration(E()) == ("listen", "1h 23m")

    class S:
        itunes_duration = "2400"
    assert _duration(S()) == ("listen", "40 min")

    class N:
        pass
    assert _duration(N()) == ("read", "")


def test_daily_brief_hides_opportunity_candidates_by_default(cfg):
    """Seeing candidates you are not allowed to start is the exact pressure the
    one-stream rule exists to remove. They are filed, not displayed."""
    scored = HeuristicScorer(cfg).score_streams([_item("Show HN: a very promising thing")])
    text = compose_daily(cfg, D, None, scored, None, Stream(), filed=3,
                         sources_ok=1, sources_total=1, sources_failed=[])
    assert "## 3 · Opportunities" in text
    assert "a very promising thing" not in text     # captured, not paraded
    assert "ideas/inbox/" in text                   # but you are told it happened
