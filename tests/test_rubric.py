from lumina.rubric import CRITERIA, RUNGS, verdict_band, weighted_total


def test_weights_sum_to_one():
    assert round(sum(c.weight for c in CRITERIA), 6) == 1.0


def test_spec_weights_are_exact():
    by_key = {c.key: c.weight for c in CRITERIA}
    assert by_key == {
        "skill_fit": 0.25, "capital": 0.20, "time_to_first_yen": 0.20,
        "proof_of_demand": 0.20, "recurring": 0.10, "time_cost": 0.05,
    }


def test_weighted_total_bounds():
    assert weighted_total({c.key: 10 for c in CRITERIA}) == 10.0
    assert weighted_total({c.key: 1 for c in CRITERIA}) == 1.0


def test_missing_criteria_are_neutral_not_zero():
    # A partial score must not read as a rejection.
    assert weighted_total({}) == 5.0


def test_bands_are_ordered():
    assert verdict_band(9)[0] == "strong"
    assert verdict_band(7)[0] == "worth a look"
    assert verdict_band(5.5)[0] == "thin"
    assert verdict_band(3)[0] == "pass"


def test_rung_ladder_is_complete():
    assert list(RUNGS) == ["1-skills", "2-productized", "3-product", "4-assets"]
