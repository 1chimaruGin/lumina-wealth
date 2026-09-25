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
    # Crypto itself is a taught track now; what gets dropped is the
    # promise-of-easy-money register, whatever asset it is attached to.
    assert is_noise(_item("Guaranteed returns, risk-free profit"))
    kept = classify_all([_item("Show HN: a CLI"), _item("Get rich quick with our trading course")])
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
    for heading in ("## 1 · Money school", "## 2 · Book", "## 3 · News",
                    "## 4 · Today's reading", "## 5 · Opportunities",
                    "## 6 · Principle", "## 7 · Today's action", "## 8 · Stream status"):
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
    assert "## 5 · Opportunities" in text
    assert "a very promising thing" not in text     # captured, not paraded
    assert "ideas/inbox/" in text                   # but you are told it happened


def test_forget_on_leaves_later_days_alone(tmp_path):
    """Rebuilding one old day must not reset the days after it."""
    from lumina.curriculum import CurriculumState

    st = CurriculumState(path=tmp_path / "c.json", taught={
        "a": "2026-09-17", "b": "2026-09-18", "c": "2026-09-19"})
    assert st.forget_on("2026-09-17") == 1
    assert set(st.taught) == {"b", "c"}


def test_forget_since_still_clears_a_whole_range(tmp_path):
    from lumina.curriculum import CurriculumState

    st = CurriculumState(path=tmp_path / "c.json", taught={
        "a": "2026-09-17", "b": "2026-09-18", "c": "2026-09-19"})
    assert st.forget_since("2026-09-18") == 2
    assert set(st.taught) == {"a"}


def test_seen_store_forget_on_is_exact(tmp_path):
    from lumina.state import SeenStore

    s = SeenStore.load(tmp_path)
    s.add("k1", source="x", title="t", first_seen="2026-09-17")
    s.add("k2", source="x", title="t", first_seen="2026-09-18")
    assert s.forget_on("2026-09-17") == 1
    assert s.has("k2") and not s.has("k1")


def test_every_state_store_has_both_forget_variants(tmp_path):
    """A patch once added forget_on to the wrong class and the suite stayed
    green, because nothing exercised PrincipleLog's copy."""
    from lumina.curriculum import CurriculumState
    from lumina.state import PrincipleLog, SeenStore

    plog = PrincipleLog(path=tmp_path / "p.json", shown={"P01": "2026-09-17", "P02": "2026-09-18"})
    assert plog.forget_on("2026-09-17") == 1
    assert set(plog.shown) == {"P02"}
    assert plog.forget_since("2026-09-18") == 1
    assert plog.shown == {}

    for store in (SeenStore.load(tmp_path), CurriculumState.load(tmp_path)):
        assert hasattr(store, "forget_on") and hasattr(store, "forget_since")


def test_profile_block_does_not_expose_raw_pattern_ids(cfg):
    """The model echoed 'You have present_bias and scattered_focus' into a
    lesson. Those are YAML keys, not English."""
    from lumina.score import profile_block

    block = profile_block(cfg)
    assert "present_bias" not in block
    assert "scattered_focus" not in block
    assert "low_capital" not in block
    # the substance must survive
    assert "short feedback loops" in block.lower()


def test_prompts_forbid_inventing_the_readers_biography():
    """A lesson asked the reader to 'think back to when you switched between
    your last two side projects'. It does not know that. Ever."""
    from lumina.score import LESSON_SYSTEM, MIND_SYSTEM

    for prompt in (LESSON_SYSTEM, MIND_SYSTEM):
        # normalise wrapping before matching
        flat = " ".join(prompt.split())
        assert "Never invent the reader's biography" in flat
        assert "You do not know what they have done" in flat


def test_lesson_schema_asks_for_a_checkable_fact_not_introspection():
    from lumina.score import LESSON_TOOL

    required = LESSON_TOOL["input_schema"]["properties"]
    assert "check" in required and "hard_truth" in required
    assert "reflection" not in required
    assert "verify" in required["check"]["description"].lower()


def test_lesson_roundtrips_the_harsh_fields(tmp_path):
    from lumina.curriculum import Lesson, Topic, load_lesson, save_lesson

    topic = Topic(id="inv-03", title="Why index funds beat most professionals",
                  scope="arithmetic", track="investing", track_name="Investing",
                  question="q", position=0)
    lesson = Lesson(topic=topic, body="Body text.", key_idea="Costs decide.",
                    hard_truth="Most active managers lose after fees.",
                    check="Find the expense ratio on your own statement.",
                    relevance="Applies to any fund you hold.", written_by="claude-code")
    save_lesson(tmp_path, lesson)
    back = load_lesson(tmp_path, topic)
    assert back.hard_truth == lesson.hard_truth
    assert back.check == lesson.check


def test_lesson_prompt_guards_against_generalised_tax_rates():
    """A generated lesson claimed FX and crypto both face 'up to 45%' in Japan.
    FX is flat 20.315%; crypto is progressive miscellaneous income. Confidently
    wrong on tax is worse than silent."""
    from lumina.score import LESSON_SYSTEM

    flat = " ".join(LESSON_SYSTEM.split())
    assert "Never generalise a rate across instruments" in flat
    assert "confirm it against the current NTA or FSA source" in flat


def test_crypto_news_survives_the_noise_filter(cfg):
    """The noise pattern listed crypto/token/nft from when they were out of
    scope. Crypto is now a taught track, and the filter was silently discarding
    every item from the crypto news source."""
    from lumina.classify import classify_all, is_noise

    for title in ("Bitcoin ETF sees record inflows", "Ethereum upgrade cuts fees",
                  "Yen weakens past 160 against the dollar"):
        assert not is_noise(_item(title, section="news"))
    kept = classify_all([_item("Bitcoin ETF sees record inflows", section="news")],
                        keep_sections={"news"})
    assert len(kept) == 1 and kept[0].section == "news"


def test_the_scam_register_is_still_filtered(cfg):
    from lumina.classify import is_noise

    for title in ("Guaranteed returns from our signal group",
                  "Get rich quick with this dropshipping course",
                  "Join the pump and dump"):
        assert is_noise(_item(title))


def test_news_keeps_its_section(cfg):
    from lumina.classify import classify_all

    item = _item("BOJ holds rates steady", section="news", source_id="boj")
    assert classify_all([item], keep_sections={"news"})[0].section == "news"


def test_news_triage_prompt_teaches_the_filter():
    from lumina.score import NEWS_SYSTEM

    flat = " ".join(NEWS_SYSTEM.split())
    assert "ignored" in flat
    assert "quiet day is a real finding" in flat
    assert "no advice to buy or sell" in flat.lower()


def test_book_note_roundtrips(tmp_path):
    from lumina.books import Book, BookNote, load_note, save_note

    b = Book(id="bk-99", title="A Book", author="Someone", year=2020, track="investing")
    n = BookNote(book=b, argument="It argues a thing.", one_idea="One idea.",
                 verdict="Read chapters 1-3 and stop.", caveat="Dated on tax.",
                 written_by="claude-code")
    save_note(tmp_path, n)
    back = load_note(tmp_path, b)
    assert back.verdict == n.verdict and back.caveat == n.caveat


def test_book_rotation_prefers_unread_then_repeats(tmp_path):
    from lumina.books import Book, BookState, next_book
    import datetime as dt

    books = [Book(id="a", title="A", author="x", weight=1.0),
             Book(id="b", title="B", author="x", weight=2.0)]
    st = BookState(path=tmp_path / "b.json", read={})
    first = next_book(books, st, dt.date(2026, 9, 26))
    assert first.id == "b"                      # higher weight first
    st.mark("b", dt.date(2026, 9, 26))
    assert next_book(books, st, dt.date(2026, 9, 27)).id == "a"
    st.mark("a", dt.date(2026, 9, 27))
    # everything read: returns to the longest ago rather than stopping
    assert next_book(books, st, dt.date(2026, 9, 28)).id == "b"
