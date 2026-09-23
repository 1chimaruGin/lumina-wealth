"""The active stream, and the gate that stops a second one starting.

streams/active.md carries YAML frontmatter (machine state) above a markdown
body (what you actually read). Everything the CLI enforces lives in the
frontmatter so nothing depends on parsing prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import yaml

from .util import parse_date, slugify, today, write_text, yen

_FM = re.compile(r"^---\s*\n(?P<fm>.*?)\n---\s*\n?(?P<body>.*)$", re.S)


def split_frontmatter(text: str) -> tuple[dict, str]:
    m = _FM.match(text)
    if not m:
        return {}, text
    return (yaml.safe_load(m.group("fm")) or {}), m.group("body")


def join_frontmatter(meta: dict, body: str) -> str:
    fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False).rstrip()
    return f"---\n{fm}\n---\n\n{body.lstrip()}"


class GateError(RuntimeError):
    """Raised when an action would break the one-stream-at-a-time rule."""


@dataclass
class Stream:
    status: str = "none"
    name: str | None = None
    slug: str | None = None
    rung: str | None = None
    started: date | None = None
    cycle_days: int = 90
    goal: str | None = None
    weekly_metric: str | None = None
    revenue_jpy: int = 0
    gate_passed: bool = False
    next_actions: list = field(default_factory=list)
    log: list = field(default_factory=list)
    body: str = ""

    # --- derived ---
    @property
    def active(self) -> bool:
        return self.status == "active" and bool(self.name)

    def day_number(self, on: date | None = None) -> int | None:
        """1-based day in the cycle. Day 1 is the start date itself."""
        if not self.started:
            return None
        return (( on or today()) - self.started).days + 1

    def days_remaining(self, on: date | None = None) -> int | None:
        n = self.day_number(on)
        return None if n is None else self.cycle_days - n + 1

    def logged_days(self) -> int:
        return len({str(e.get("date")) for e in self.log if e.get("date")})

    def actions_since(self, since: date) -> int:
        return len([e for e in self.log if e.get("action") and parse_date(e.get("date")) and parse_date(e["date"]) >= since])

    def actions_on(self, day: date) -> list[dict]:
        return [e for e in self.log if parse_date(e.get("date")) == day]

    def revenue_to(self, on: date) -> int:
        """Revenue recorded up to and including `on` — so a backfilled brief
        shows the number as it stood that day, not today's number."""
        return sum(int(e.get("revenue") or 0) for e in self.log if parse_date(e.get("date")) and parse_date(e["date"]) <= on)

    def metric_value(self, on: date | None = None) -> str:
        """This week's count of logged actions — the default weekly metric."""
        on = on or today()
        monday = on - timedelta(days=on.weekday())
        return f"{self.actions_since(monday)} actions logged this week"

    # --- serialisation ---
    def to_meta(self) -> dict:
        return {
            "status": self.status,
            "name": self.name,
            "slug": self.slug,
            "rung": self.rung,
            "started": str(self.started) if self.started else None,
            "cycle_days": self.cycle_days,
            "goal": self.goal,
            "weekly_metric": self.weekly_metric,
            "revenue_jpy": self.revenue_jpy,
            "gate_passed": self.gate_passed,
            "next_actions": self.next_actions,
            "log": self.log,
        }

    @classmethod
    def from_meta(cls, meta: dict, body: str = "") -> "Stream":
        meta = meta or {}
        return cls(
            status=meta.get("status", "none") or "none",
            name=meta.get("name"),
            slug=meta.get("slug"),
            rung=meta.get("rung"),
            started=parse_date(meta.get("started")),
            cycle_days=int(meta.get("cycle_days") or 90),
            goal=meta.get("goal"),
            weekly_metric=meta.get("weekly_metric"),
            revenue_jpy=int(meta.get("revenue_jpy") or 0),
            gate_passed=bool(meta.get("gate_passed")),
            next_actions=list(meta.get("next_actions") or []),
            log=list(meta.get("log") or []),
            body=body,
        )


def load_stream(path: Path | str) -> Stream:
    path = Path(path)
    if not path.exists():
        return Stream()
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return Stream.from_meta(meta, body)


def save_stream(path: Path | str, stream: Stream, body: str | None = None) -> Path:
    return write_text(path, join_frontmatter(stream.to_meta(), body if body is not None else stream.body))


# --- the gate ---------------------------------------------------------------


@dataclass
class GateResult:
    passed: bool
    route: str | None
    reasons: list[str]
    checks: list[tuple[str, bool, str]]

    def render(self) -> str:
        lines = []
        for label, ok, detail in self.checks:
            lines.append(f"  [{'x' if ok else ' '}] {label}: {detail}")
        head = f"GATE {'PASSED' if self.passed else 'NOT PASSED'}"
        if self.route:
            head += f" (route {self.route})"
        return head + "\n" + "\n".join(lines)


def check_gate(stream: Stream, gate_cfg: dict, on: date | None = None) -> GateResult:
    """Two ways through, and only two.

    Route A — it worked: first revenue AND a routine that actually held.
    Route B — it is over: the full cycle ran and a written decision exists.

    Anything else and the answer is no. That is the entire anti-scatter
    mechanism; everything else in this repo just feeds it.
    """
    on = on or today()
    gate_cfg = gate_cfg or {}
    min_rev = int(gate_cfg.get("min_revenue_jpy", 1))
    min_days = int(gate_cfg.get("min_logged_days", 14))
    window = int(gate_cfg.get("routine_window_days", 21))
    min_actions = int(gate_cfg.get("min_actions_in_window", 10))

    if not stream.active:
        return GateResult(True, "no active stream", ["No stream is active — a slot is free."],
                          [("active stream", False, "none")])

    revenue = stream.revenue_jpy or stream.revenue_to(on)
    logged = stream.logged_days()
    recent = stream.actions_since(on - timedelta(days=window))
    day_n = stream.day_number(on) or 0
    cycle_done = day_n >= stream.cycle_days

    checks_a = [
        ("first revenue", revenue >= min_rev, f"{yen(revenue)} of {yen(min_rev)}"),
        ("days logged", logged >= min_days, f"{logged} of {min_days}"),
        (f"actions in last {window} days", recent >= min_actions, f"{recent} of {min_actions}"),
    ]
    route_a = all(ok for _, ok, _ in checks_a)

    checks_b = [
        (f"{stream.cycle_days}-day cycle complete", cycle_done, f"day {day_n} of {stream.cycle_days}"),
    ]
    route_b = cycle_done  # the written decision is verified by `archive`, which writes it

    checks = [("— Route A: first revenue + routine —", route_a, "pass" if route_a else "not yet")] + checks_a
    checks += [("— Route B: cycle complete + written decision —", route_b, "pass" if route_b else "not yet")] + checks_b

    if route_a:
        return GateResult(True, "A", ["First revenue with a routine that held."], checks)
    if route_b:
        return GateResult(
            True, "B",
            [f"The {stream.cycle_days} days are done. Run `stream.py archive` with a kill or pivot decision."],
            checks,
        )

    reasons = [f"'{stream.name}' is on day {day_n} of {stream.cycle_days} and has not met route A."]
    missing = [label for label, ok, _ in checks_a if not ok]
    if missing:
        reasons.append("Still needed for route A: " + ", ".join(missing) + ".")
    reasons.append(f"Or wait {max(0, stream.cycle_days - day_n)} more days and archive it with a written decision.")
    return GateResult(False, None, reasons, checks)


def archive_path(root: Path, stream: Stream, on: date) -> Path:
    return Path(root) / "streams" / "archive" / f"{on}-{stream.slug or slugify(stream.name or 'stream')}.md"
