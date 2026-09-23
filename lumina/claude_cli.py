"""Scoring through the Claude Code CLI instead of the Anthropic API.

Why this exists: a Claude Max subscription includes Claude Code but does not
come with an `ANTHROPIC_API_KEY`. The CLI authenticates against the
subscription, so the whole pipeline runs with no API key and no per-call
billing — locally from an interactive login, and in CI from a long-lived token
made with `claude setup-token`.

The trade-off against the API backend is structured output: headless Claude
Code has no forced tool use, so the schema is described in the prompt and the
reply is parsed defensively. Anything that does not parse falls back to the
offline scorer for that batch, exactly like every other failure here.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .util import log

# Claude Code loads its own agent prompt and tool definitions on every run.
# Keeping the system prompt byte-identical between calls lets the server-side
# prompt cache absorb almost all of it (~26K cached vs ~4K new per call).
_EMPTY_MCP = '{"mcpServers":{}}'

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.M)


class ClaudeCodeError(RuntimeError):
    pass


def cli_available() -> bool:
    return shutil.which("claude") is not None


def describe_schema(input_schema: dict) -> str:
    """Render a tool's input_schema as instructions.

    The API backend hands this schema to the model as a forced tool; here it
    has to be prose, so the two backends stay in sync by reading the same dict.
    """
    def one(name: str, spec: dict, indent: str = "  ") -> list[str]:
        kind = spec.get("type", "any")
        bits = [f"{indent}{name}: {kind}"]
        if spec.get("enum"):
            bits[0] += " — one of " + ", ".join(f'"{v}"' for v in spec["enum"])
        if kind == "integer" and "minimum" in spec:
            bits[0] += f" ({spec['minimum']}–{spec.get('maximum', '?')})"
        if spec.get("description"):
            bits[0] += f" — {spec['description']}"
        return bits

    props = input_schema.get("properties", {})
    lines: list[str] = []
    for key, spec in props.items():
        if spec.get("type") == "array" and spec.get("items", {}).get("properties"):
            lines.append(f"  {key}: array of objects, each with:")
            for sub, subspec in spec["items"]["properties"].items():
                lines += one(sub, subspec, indent="    - ")
        else:
            lines += one(key, spec)
    return "\n".join(lines)


def extract_json(text: str) -> dict:
    """Pull a JSON object out of a reply that may be fenced or padded.

    Models wrap JSON in ``` fences often enough that stripping them is not a
    workaround, it is the expected shape.
    """
    if not text:
        raise ClaudeCodeError("empty reply")
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    if start == -1:
        raise ClaudeCodeError("no JSON object in reply")
    depth, in_string, escaped = 0, False, False
    for i, ch in enumerate(cleaned[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start : i + 1])
                except json.JSONDecodeError as exc:
                    raise ClaudeCodeError(f"malformed JSON: {exc}") from exc
    raise ClaudeCodeError("unterminated JSON object")


class ClaudeCodeClient:
    """One headless `claude -p` call per request, returning parsed JSON."""

    def __init__(self, model: str = "haiku", timeout: int = 180, cwd: Path | None = None):
        self.model = model
        self.timeout = timeout
        self.cwd = str(cwd or Path(tempfile.gettempdir()))
        self._mcp_file: str | None = None

    def _mcp_config(self) -> str:
        # A file rather than inline JSON: the flag takes paths, and an empty
        # server list is what keeps project MCP servers out of the run.
        if self._mcp_file is None:
            fd, path = tempfile.mkstemp(prefix="lumina-mcp-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(_EMPTY_MCP)
            self._mcp_file = path
        return self._mcp_file

    def ask(self, system: str, user: str) -> tuple[dict, dict]:
        """Returns (parsed_json, usage). Raises ClaudeCodeError on any failure."""
        cmd = [
            "claude", "-p", user,
            "--output-format", "json",
            "--model", self.model,
            "--system-prompt", system,   # replaces the default agent prompt
            "--allowedTools", "",        # this is a text task; no tools at all
            "--strict-mcp-config",
            "--mcp-config", self._mcp_config(),
            "--no-session-persistence",
        ]
        env = {**os.environ}
        # Never let a stray key silently switch billing to the API.
        env.pop("ANTHROPIC_API_KEY", None)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout,
                cwd=self.cwd, env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCodeError(f"timed out after {self.timeout}s") from exc
        except FileNotFoundError as exc:
            raise ClaudeCodeError("the `claude` CLI is not installed") from exc

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            raise ClaudeCodeError(f"exit {proc.returncode}: {detail[-1][:160] if detail else 'no output'}")

        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ClaudeCodeError(f"CLI did not return JSON: {exc}") from exc

        if envelope.get("is_error"):
            raise ClaudeCodeError(str(envelope.get("result", "unknown CLI error"))[:160])

        usage = envelope.get("usage") or {}
        stats = {
            "input_tokens": int(usage.get("input_tokens") or 0)
            + int(usage.get("cache_creation_input_tokens") or 0)
            + int(usage.get("cache_read_input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            # Reported by the CLI as the equivalent API price. On a Max plan
            # nothing is billed per call, so this is a size signal, not a bill.
            "equivalent_usd": float(envelope.get("total_cost_usd") or 0.0),
        }
        return extract_json(envelope.get("result", "")), stats

    def close(self) -> None:
        if self._mcp_file:
            Path(self._mcp_file).unlink(missing_ok=True)
            self._mcp_file = None


def auth_hint() -> str:
    """What to tell someone whose CLI is present but unauthenticated."""
    if os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):
        return "CLAUDE_CODE_OAUTH_TOKEN is set but was rejected — regenerate it with `claude setup-token`."
    return "Run `claude` once to sign in, or set CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`."
