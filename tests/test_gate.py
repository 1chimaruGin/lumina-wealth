"""The anti-scatter gate. If these break, the whole system's promise breaks."""

from datetime import date, timedelta

from lumina.streams import Stream, check_gate, load_stream, save_stream

GATE = {
    "min_revenue_jpy": 1, "min_logged_days": 14,
    "routine_window_days": 21, "min_actions_in_window": 10,
}
TODAY = date(2026, 9, 23)


def _stream(**kw):
    base = dict(status="active", name="Test stream", slug="test-stream", rung="1-skills",
                started=TODAY - timedelta(days=20), cycle_days=90, log=[])
    base.update(kw)
    return Stream(**base)


def _reps(n, end=TODAY, revenue=0):
    log = [{"date": str(end - timedelta(days=i)), "action": f"rep {i}", "minutes": 10} for i in range(n)]
    if revenue:
        log.append({"date": str(end - timedelta(days=1)), "revenue": revenue})
    return log


def test_no_stream_means_slot_open():
    assert check_gate(Stream(), GATE, on=TODAY).passed


def test_fresh_stream_is_blocked():
    result = check_gate(_stream(), GATE, on=TODAY)
    assert not result.passed and result.route is None


def test_revenue_alone_is_not_enough():
    # Money without a routine is luck, not a stream.
    s = _stream(log=[{"date": str(TODAY), "revenue": 50000}], revenue_jpy=50000)
    assert not check_gate(s, GATE, on=TODAY).passed


def test_routine_alone_is_not_enough():
    s = _stream(log=_reps(20))
    assert not check_gate(s, GATE, on=TODAY).passed


def test_route_a_needs_revenue_and_routine():
    s = _stream(log=_reps(15, revenue=45000), revenue_jpy=45000)
    result = check_gate(s, GATE, on=TODAY)
    assert result.passed and result.route == "A"


def test_route_b_opens_at_cycle_end():
    s = _stream(started=TODAY - timedelta(days=89), cycle_days=90)
    result = check_gate(s, GATE, on=TODAY)
    assert result.passed and result.route == "B"


def test_route_b_not_open_one_day_early():
    s = _stream(started=TODAY - timedelta(days=88), cycle_days=90)
    assert not check_gate(s, GATE, on=TODAY).passed


def test_stale_routine_fails_even_with_revenue():
    # 15 reps, but all of them more than 21 days ago.
    old = TODAY - timedelta(days=40)
    s = _stream(log=_reps(15, end=old, revenue=45000), revenue_jpy=45000)
    assert not check_gate(s, GATE, on=TODAY).passed


def test_day_number_starts_at_one():
    s = _stream(started=TODAY)
    assert s.day_number(TODAY) == 1


def test_revenue_to_date_is_point_in_time():
    # A backfilled brief must show the number as it stood that day.
    s = _stream(log=[
        {"date": str(TODAY - timedelta(days=5)), "revenue": 10000},
        {"date": str(TODAY), "revenue": 25000},
    ])
    assert s.revenue_to(TODAY - timedelta(days=1)) == 10000
    assert s.revenue_to(TODAY) == 35000


def test_roundtrip_through_frontmatter(tmp_path):
    s = _stream(log=_reps(3), revenue_jpy=1234, goal="¥100,000", weekly_metric="calls")
    path = tmp_path / "active.md"
    save_stream(path, s, "# body\n")
    back = load_stream(path)
    assert back.name == s.name and back.revenue_jpy == 1234
    assert back.started == s.started and len(back.log) == 3
    assert back.goal == "¥100,000"
