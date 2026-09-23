"""The scoring rubric — data, not logic, so it can be tuned in one place."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    weight: float
    question: str
    guidance: str


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "skill_fit", "Skill fit", 0.25,
        "Can my engineering/AI skills deliver this now?",
        "10 = squarely Python/backend/AI/cloud work I could start tonight. "
        "5 = adjacent, a weekend of learning. 1 = needs a skill set I do not have "
        "(design, sales-heavy, hardware, licences).",
    ),
    Criterion(
        "capital", "Capital needed", 0.20,
        "Can it start at ~¥0?",
        "10 = free (own time and a laptop only). 5 = under ¥20,000 to start. "
        "1 = meaningful upfront money, inventory, or a registered company.",
    ),
    Criterion(
        "time_to_first_yen", "Time to first yen", 0.20,
        "Could it earn within ~30 days?",
        "10 = a first payment is plausible inside two weeks. 5 = one to three months. "
        "1 = six months or more of building before any revenue.",
    ),
    Criterion(
        "proof_of_demand", "Proof of demand", 0.20,
        "Are people already paying for something similar?",
        "10 = named competitors with paying customers, or people in the thread saying "
        "they already pay for this. 5 = clear complaints and ugly workarounds but no "
        "money visible. 1 = nobody has asked for it.",
    ),
    Criterion(
        "recurring", "Recurring potential", 0.10,
        "Could it become monthly income?",
        "10 = subscription or retainer by nature. 5 = repeat projects from the same "
        "clients. 1 = strictly one-off.",
    ),
    Criterion(
        "time_cost", "Time cost", 0.05,
        "Does it fit around a full-time job?",
        "10 = a few focused hours a week, asynchronous. 5 = needs some weekday "
        "daytime availability. 1 = needs full-time attention or same-timezone calls "
        "during work hours.",
    ),
)

CRITERION_KEYS = tuple(c.key for c in CRITERIA)

RUNGS: dict[str, str] = {
    "1-skills": "Freelance / consulting — selling hours directly.",
    "2-productized": "Productized service — fixed scope, fixed price, repeatable.",
    "3-product": "Product — software that sells without bespoke delivery.",
    "4-assets": "Assets — things that earn whether or not you show up.",
}


def weighted_total(scores: dict[str, float]) -> float:
    """Weighted 1-10 total. Missing criteria count as 5 (neutral) rather than 0,
    so a partial score never looks like a rejection."""
    total = sum(float(scores.get(c.key, 5)) * c.weight for c in CRITERIA)
    return round(min(10.0, max(1.0, total)), 2)


def verdict_band(total: float) -> tuple[str, str]:
    """(label, what to do about it) — the one-line verdict's backbone."""
    if total >= 8.0:
        return "strong", "Candidate for the next slot. Park it and keep going."
    if total >= 6.5:
        return "worth a look", "Worth 15 minutes of digging when the current stream gates."
    if total >= 5.0:
        return "thin", "Filed for pattern-matching only."
    return "pass", "Logged, not pursued."


def rubric_markdown() -> str:
    lines = ["| Criterion | Weight | Question |", "|---|---|---|"]
    for c in CRITERIA:
        lines.append(f"| {c.label} | {int(c.weight * 100)}% | {c.question} |")
    return "\n".join(lines)
