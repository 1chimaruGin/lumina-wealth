"""Persistent state: dedupe, token spend, principle rotation, run history.

All of it is JSON in data/ so it diffs readably in git and can be hand-fixed.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from .util import append_jsonl, log, read_json, today, write_json

# Tracking junk that makes the same article look like two.
_TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_cid|mc_eid|ref_?$|source$)", re.I)


def canonical_url(url: str) -> str:
    """Normalise a URL enough that the same article from two sources collapses."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    scheme = "https"
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc.endswith(":443"):
        netloc = netloc[:-4]
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)])
    return urlunsplit((scheme, netloc, path, query, ""))


def item_key(url: str, title: str = "") -> str:
    """Prefer the URL; fall back to the title for feeds with unstable links."""
    basis = canonical_url(url) or f"title:{re.sub(r'[^a-z0-9]+', '', (title or '').lower())}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


@dataclass
class SeenStore:
    """data/seen.json — dedupe across runs.

    Deliberately stores no article text: key, source, first-seen date and a
    trimmed title, which is the minimum needed to not show something twice.
    """

    path: Path
    entries: dict
    retention_days: int = 400

    @classmethod
    def load(cls, data_dir: Path, retention_days: int = 400) -> "SeenStore":
        path = Path(data_dir) / "seen.json"
        raw = read_json(path, default={}) or {}
        return cls(path=path, entries=raw.get("items", raw) if isinstance(raw, dict) else {},
                   retention_days=retention_days)

    def has(self, key: str) -> bool:
        return key in self.entries

    def add(self, key: str, *, source: str, title: str, first_seen: date | str | None = None) -> None:
        if key in self.entries:
            return
        self.entries[key] = {
            "source": source,
            "title": (title or "")[:140],
            "first_seen": str(first_seen or today()),
        }

    def forget_since(self, d: date | str) -> int:
        """Drop everything first seen on or after `d`.

        Without this, rebuilding a day is not idempotent: the previous run
        already marked its own picks as seen, so the rebuild silently produces
        a thinner brief from the leftovers.
        """
        cutoff = str(d)
        stale = [k for k, v in self.entries.items() if str(v.get("first_seen", "")) >= cutoff]
        for k in stale:
            del self.entries[k]
        return len(stale)

    def prune(self) -> int:
        cutoff = str(today() - timedelta(days=self.retention_days))
        stale = [k for k, v in self.entries.items() if str(v.get("first_seen", "")) < cutoff]
        for k in stale:
            del self.entries[k]
        return len(stale)

    def save(self) -> None:
        pruned = self.prune()
        if pruned:
            log.debug("pruned %d stale seen-entries", pruned)
        write_json(self.path, {"items": self.entries, "count": len(self.entries)})


@dataclass
class UsageStore:
    """data/usage.json — token spend per run, and the budget ceiling.

    The budget is a *stop*, never a failure: when it trips, scoring halts and
    the brief is composed from whatever was already scored.
    """

    path: Path
    history: list
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    price_in: float = 1.0
    price_out: float = 5.0
    max_input: int = 120_000
    max_output: int = 30_000
    max_usd: float = 0.25
    max_calls: int = 40
    # False for subscription-billed backends (Claude Code): the CLI still
    # reports an equivalent API price, but nothing is charged per call, so the
    # dollar ceiling would stop a run over a bill that does not exist.
    billed: bool = True
    equivalent_usd: float = 0.0
    stopped_reason: str | None = None

    @classmethod
    def load(cls, data_dir: Path, budget: dict) -> "UsageStore":
        path = Path(data_dir) / "usage.json"
        raw = read_json(path, default={"runs": []}) or {"runs": []}
        return cls(
            path=path,
            history=raw.get("runs", []),
            price_in=float(budget.get("price_per_mtok_input", 1.0)),
            price_out=float(budget.get("price_per_mtok_output", 5.0)),
            max_input=int(budget.get("max_input_tokens_per_run", 120_000)),
            max_output=int(budget.get("max_output_tokens_per_run", 30_000)),
            max_usd=float(budget.get("max_usd_per_run", 0.25)),
            max_calls=int(budget.get("max_calls_per_run", 40)),
        )

    @property
    def cost_usd(self) -> float:
        return (self.input_tokens / 1e6) * self.price_in + (self.output_tokens / 1e6) * self.price_out

    def record(self, input_tokens: int, output_tokens: int, equivalent_usd: float = 0.0) -> None:
        self.input_tokens += int(input_tokens or 0)
        self.output_tokens += int(output_tokens or 0)
        self.equivalent_usd += float(equivalent_usd or 0.0)
        self.calls += 1

    def exhausted(self) -> str | None:
        """Reason the budget is spent, or None. Checked before each API call."""
        if self.stopped_reason:
            return self.stopped_reason
        if self.calls >= self.max_calls:
            self.stopped_reason = f"call ceiling reached ({self.calls}/{self.max_calls})"
        elif self.input_tokens >= self.max_input:
            self.stopped_reason = f"input token ceiling reached ({self.input_tokens:,}/{self.max_input:,})"
        elif self.output_tokens >= self.max_output:
            self.stopped_reason = f"output token ceiling reached ({self.output_tokens:,}/{self.max_output:,})"
        elif self.billed and self.cost_usd >= self.max_usd:
            self.stopped_reason = f"cost ceiling reached (${self.cost_usd:.4f}/${self.max_usd:.2f})"
        return self.stopped_reason

    def summary(self) -> dict:
        out = {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "billed": self.billed,
            "stopped": self.stopped_reason,
        }
        if self.billed:
            out["cost_usd"] = round(self.cost_usd, 5)
        else:
            # Named so a subscription run is never read as a bill.
            out["equivalent_usd_not_charged"] = round(self.equivalent_usd, 5)
            out["cost_usd"] = 0.0
        return out

    def save(self, run_label: str, extra: dict | None = None) -> None:
        entry = {"run": run_label, "at": str(today()), **self.summary(), **(extra or {})}
        self.history = (self.history + [entry])[-400:]
        totals = {
            "input_tokens": sum(r.get("input_tokens", 0) for r in self.history),
            "output_tokens": sum(r.get("output_tokens", 0) for r in self.history),
            "cost_usd": round(sum(r.get("cost_usd", 0.0) for r in self.history), 4),
        }
        write_json(self.path, {"runs": self.history, "totals_last_400_runs": totals})


@dataclass
class PrincipleLog:
    """data/principles.json — which principle was shown on which day.

    Kept out of principles.md so that file stays a clean, hand-editable document.
    """

    path: Path
    shown: dict

    @classmethod
    def load(cls, data_dir: Path) -> "PrincipleLog":
        path = Path(data_dir) / "principles.json"
        raw = read_json(path, default={"shown": {}}) or {}
        return cls(path=path, shown=raw.get("shown", {}))

    def last_shown(self, pid: str) -> date | None:
        value = self.shown.get(pid)
        return date.fromisoformat(value) if value else None

    def forget_since(self, d: date | str) -> int:
        """Drop marks on or after `d`, so a rebuilt range replays the same
        rotation instead of drifting each time it is rebuilt."""
        cutoff = str(d)
        stale = [k for k, v in self.shown.items() if str(v) >= cutoff]
        for k in stale:
            del self.shown[k]
        return len(stale)

    def mark(self, pid: str, on: date) -> None:
        # Backfill replays in date order; keep the latest date only.
        existing = self.shown.get(pid)
        if not existing or str(on) > existing:
            self.shown[pid] = str(on)

    def save(self) -> None:
        write_json(self.path, {"shown": self.shown})


def log_run(data_dir: Path, record: dict) -> None:
    """data/runs.jsonl — an append-only trail of every run, for the dashboard."""
    append_jsonl(Path(data_dir) / "runs.jsonl", record)
