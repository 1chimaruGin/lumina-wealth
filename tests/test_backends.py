"""Backend selection, JSON extraction, and subscription-aware budgeting."""

import json

import pytest

from lumina import claude_cli
from lumina.claude_cli import ClaudeCodeError, describe_schema, extract_json
from lumina.score import SCORE_TOOL, HeuristicScorer, build_scorer
from lumina.state import UsageStore


# --- JSON extraction: the CLI has no forced tool use, so parsing is the contract ---

def test_extracts_bare_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extracts_fenced_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extracts_json_with_surrounding_prose():
    assert extract_json('Sure, here it is:\n{"a": {"b": 2}}\nHope that helps!') == {"a": {"b": 2}}


def test_braces_inside_strings_do_not_confuse_the_scanner():
    payload = '{"verdict": "use {braces} freely", "n": 1}'
    assert extract_json("noise " + payload)["verdict"] == "use {braces} freely"


def test_escaped_quote_inside_string():
    assert extract_json(r'{"s": "a \"quoted\" word"}')["s"] == 'a "quoted" word'


@pytest.mark.parametrize("bad", ["", "no json here", "{unterminated: "])
def test_unparseable_replies_raise(bad):
    with pytest.raises(ClaudeCodeError):
        extract_json(bad)


def test_schema_description_covers_every_required_key():
    described = describe_schema(SCORE_TOOL["input_schema"])
    for key in SCORE_TOOL["input_schema"]["properties"]["items"]["items"]["required"]:
        assert key in described


# --- backend selection ---

def test_no_llm_always_means_offline(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(claude_cli, "cli_available", lambda: True)
    usage = UsageStore.load(tmp_path, {})
    assert build_scorer(cfg, usage, use_llm=False).name == "heuristic"


def test_env_override_wins_over_settings(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_BACKEND", "offline")
    monkeypatch.setattr(claude_cli, "cli_available", lambda: True)
    assert build_scorer(cfg, UsageStore.load(tmp_path, {})).name == "heuristic"


def test_claude_code_backend_degrades_when_cli_missing(cfg, tmp_path, monkeypatch):
    # No CLI and no key: offline, not a crash.
    monkeypatch.setenv("LUMINA_BACKEND", "claude-code")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(claude_cli, "cli_available", lambda: False)
    assert build_scorer(cfg, UsageStore.load(tmp_path, {})).name == "heuristic"


def test_api_backend_without_key_degrades(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_BACKEND", "api")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert build_scorer(cfg, UsageStore.load(tmp_path, {})).name == "heuristic"


def test_unknown_backend_degrades(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("LUMINA_BACKEND", "telepathy")
    assert build_scorer(cfg, UsageStore.load(tmp_path, {})).name == "heuristic"


def test_settings_default_to_claude_code(cfg):
    assert cfg.get("model.backend") == "claude-code"


# --- budget: a subscription run must not stop over a bill nobody pays ---

def test_subscription_run_ignores_the_dollar_ceiling(tmp_path):
    usage = UsageStore.load(tmp_path, {"max_usd_per_run": 0.01, "max_calls_per_run": 50})
    usage.billed = False
    usage.record(30_000, 8_000, equivalent_usd=5.0)
    assert usage.exhausted() is None
    assert usage.summary()["cost_usd"] == 0.0
    assert usage.summary()["equivalent_usd_not_charged"] == 5.0


def test_billed_run_still_stops_on_the_dollar_ceiling(tmp_path):
    usage = UsageStore.load(tmp_path, {"max_usd_per_run": 0.001, "max_calls_per_run": 50})
    usage.record(5_000, 5_000)
    assert "cost ceiling" in usage.exhausted()


def test_call_ceiling_stops_a_subscription_run(tmp_path):
    usage = UsageStore.load(tmp_path, {"max_calls_per_run": 2})
    usage.billed = False
    usage.record(10, 10)
    assert usage.exhausted() is None
    usage.record(10, 10)
    assert "call ceiling" in usage.exhausted()


def test_usage_json_names_subscription_spend_unambiguously(tmp_path):
    usage = UsageStore.load(tmp_path, {})
    usage.billed = False
    usage.record(100, 10, equivalent_usd=0.5)
    usage.save("test")
    saved = json.loads((tmp_path / "usage.json").read_text())
    entry = saved["runs"][-1]
    assert entry["billed"] is False
    assert entry["cost_usd"] == 0.0
    assert entry["equivalent_usd_not_charged"] == 0.5
