"""Scoring and summarising.

Two implementations behind one interface:

  ClaudeScorer     — Haiku 4.5 via the Anthropic SDK, forced tool use so the
                     response is always schema-valid JSON.
  HeuristicScorer  — no network, no key, deterministic. Used by --no-llm, by
                     the tests, and as the automatic fallback when the budget
                     runs out mid-run or the API is unreachable.

The budget is a stop, never a failure: when it trips, the remaining items fall
through to the heuristic and the brief says so in Run notes.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Sequence

from .collect import Item
from .config import Config
from .rubric import CRITERIA, CRITERION_KEYS, RUNGS, verdict_band, weighted_total
from .state import UsageStore
from .util import clip_words, log, one_line


@dataclass
class StreamScore:
    item: Item
    scores: dict[str, int]
    rung: str
    opportunity: str
    verdict: str
    why_now: str = ""
    scored_by: str = "heuristic"

    @property
    def total(self) -> float:
        return weighted_total(self.scores)

    @property
    def band(self) -> str:
        return verdict_band(self.total)[0]

    @property
    def action(self) -> str:
        return verdict_band(self.total)[1]

    def to_frontmatter(self) -> dict:
        return {
            "title": self.item.title,
            "url": self.item.url,
            "source": self.item.source_name,
            "source_id": self.item.source_id,
            "date": str(self.item.published_date or ""),
            "score": self.total,
            "rung": self.rung,
            "scores": self.scores,
            "status": "inbox",
            "scored_by": self.scored_by,
        }


@dataclass
class MindPiece:
    item: Item
    summary: str
    key_idea: str
    catch: str = ""
    summarised_by: str = "heuristic"


# --- prompts ---------------------------------------------------------------

_RUNG_LIST = "\n".join(f"  {k}: {v}" for k, v in RUNGS.items())
_CRITERIA_BLOCK = "\n".join(
    f"  {c.key} (weight {int(c.weight*100)}%) — {c.question}\n    {c.guidance}" for c in CRITERIA
)

SCORE_SYSTEM = f"""You score income-stream opportunities for one specific person.
You are blunt and calibrated. Most things are mediocre for this person; say so.
A 7+ should be rare and mean "genuinely worth their next 90 days".

Score each item 1-10 on every criterion:
{_CRITERIA_BLOCK}

Also assign the ladder rung:
{_RUNG_LIST}

Rules:
- Judge the OPPORTUNITY the item implies for this person, not the item's own quality.
  A launch post about a $2M-ARR product is evidence of demand for that niche; it is
  not itself an opportunity to clone.
- "opportunity" must be a concrete thing THIS person could sell, in <= 18 words.
- "why_now" is the demand evidence you actually saw in the item, in <= 20 words.
  If there is none, say "no demand evidence in the item".
- "verdict" is one line, <= 22 words, ending in a recommendation. Be direct.
- Never invent facts, revenue figures, or customers that were not in the item.
"""

MIND_SYSTEM = """You write the reading note in a daily money brief, for a reader who has
asked for the blunt version and has no patience for filler.

Given one article's title and a short excerpt, write:
- summary: what the piece argues, 60-110 words, plain English, your own words.
- key_idea: the single transferable idea, one sentence, <= 25 words.
- catch: what the piece leaves out, assumes, or gets wrong — <= 40 words. Who
  benefits from this framing, what the survivorship or selection problem is, or
  what it would cost to act on. If the piece is simply sound, say what it does
  NOT cover rather than inventing a flaw.

Hard rules:
- You have only a short excerpt. Do not invent specifics, statistics or examples
  that are not in it. If the excerpt is thin, keep it general rather than
  fabricating detail, and do not pretend to have read the whole piece.
- Never reproduce the article's sentences. Summarise in your own words only.
- Never invent the reader's biography or ask them to recall their own past. You
  do not know what they have done.
- No motivational padding.
- Refer to the reader's habits in plain English. Never echo an identifier,
  a field name, or snake_case text from the profile you were given.
"""

SCORE_TOOL = {
    "name": "record_scores",
    "description": "Record the rubric scores for every item in the batch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "The item id given in the prompt."},
                        **{
                            k: {"type": "integer", "minimum": 1, "maximum": 10}
                            for k in CRITERION_KEYS
                        },
                        "rung": {"type": "string", "enum": list(RUNGS)},
                        "opportunity": {"type": "string"},
                        "why_now": {"type": "string"},
                        "verdict": {"type": "string"},
                    },
                    "required": ["id", *CRITERION_KEYS, "rung", "opportunity", "why_now", "verdict"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    },
    "strict": True,
}

MIND_TOOL = {
    "name": "record_mind_piece",
    "description": "Record the summary, key idea, and the catch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "key_idea": {"type": "string"},
            "catch": {"type": "string"},
        },
        "required": ["summary", "key_idea", "catch"],
        "additionalProperties": False,
    },
    "strict": True,
}


LESSON_SYSTEM = """You write one lesson in a money curriculum for a reader who has asked,
explicitly, for the harsh version. Take that seriously.

They are a salaried software engineer in Tokyo who wants to understand money,
investing and markets properly. They have said plainly that they find invented,
introspective prompts worthless. They are right.

Write:
- body: 260-340 words. Plain English, your own words. Lead with the mechanism or
  the number, not with context-setting. Be concrete: real figures, real dates,
  real base rates where the topic has them. If a claim has a number attached in
  the literature, give the number.
- key_idea: the one transferable sentence, <= 28 words.
- hard_truth: the uncomfortable part most explanations leave out — <= 45 words.
  What does this cost, who is on the other side, what are the actual odds, what
  does it mean for someone without capital. If the honest answer is "this mostly
  does not work for people like you", write that.
- check: ONE concrete thing they can verify, compute or look up — a number to
  work out, a fee to find on a real statement, a base rate to check. It must be
  answerable from facts, never from recalling their own feelings or past.
- relevance: one sentence, <= 30 words, on what this changes for a salaried
  engineer in Tokyo.

Tone: direct and unsentimental. No motivational padding, no "the good news is",
no reassurance the facts do not support. Respect costs them nothing.

Hard rules:
- Accuracy beats encouragement. Where the honest answer is discouraging, say it
  and give the number.
- Never invent statistics, quotations or dates. If unsure of a figure, describe
  the magnitude qualitatively and say it is approximate.
- Tax and regulation are where confident answers go wrong. Different instruments
  in the same country are taxed under completely different regimes — in Japan,
  listed equities and 店頭FX are flat 20.315% separate taxation, while crypto is
  雑所得 taxed progressively. Never generalise a rate across instruments. If you
  state any rate, limit or rule, name the exact instrument it applies to and add
  that the reader should confirm it against the current NTA or FSA source,
  because these change.
- Never invent the reader's biography. You do not know what they have done,
  bought, tried or abandoned. Do not write "think back to when you...".
- This is education, not advice. Explain how instruments and markets work and
  what the evidence says. Never tell them what to buy, sell or hold.
- Refer to the reader's habits in plain English. Never echo an identifier,
  a field name, or snake_case text from the profile you were given.
"""

LESSON_TOOL = {
    "name": "record_lesson",
    "description": "Record the written lesson.",
    "input_schema": {
        "type": "object",
        "properties": {
            "body": {"type": "string", "description": "260-340 words of teaching."},
            "key_idea": {"type": "string"},
            "hard_truth": {"type": "string", "description": "The uncomfortable part most explanations omit."},
            "check": {"type": "string", "description": "Something factual to verify or compute. Never introspection."},
            "relevance": {"type": "string"},
        },
        "required": ["body", "key_idea", "hard_truth", "check", "relevance"],
        "additionalProperties": False,
    },
    "strict": True,
}


BOOK_SYSTEM = """You write the daily book note for a reader who asked for the blunt version.

This is not a review and not a recommendation. The reader's scarcest resource is
hours, and most money books are one genuine insight padded to two hundred pages.
Your job is to tell them which this is.

Write:
- argument: what the book actually claims, 3 sentences, your own words.
- one_idea: the single transferable idea worth keeping if they read nothing else,
  <= 30 words.
- verdict: worth their hours or not, and in what form. Be specific and be willing
  to say "the summary above is enough" or "read chapters 1-4 and stop". If it IS
  worth reading in full, say that too — but only when it earns it.
- caveat: what it gets wrong, what has dated badly, whose interests it serves, or
  who should not bother. <= 45 words. Every book has one; find the real one
  rather than a token criticism.

Hard rules:
- Judge the book, not its reputation. A classic can be outdated; a bestseller can
  be one blog post. Say so.
- Judge the BOOK, not the reader. Do not predict what they will do, whether they
  will finish it, or what they "know about themselves". You may note that a book
  is long, dense or slow — that is a fact about the book. "You will abandon it"
  is not.
- "Does this earn money" is not the test. They are learning how money works; a
  history or a critique can be worth the hours on its own terms.
- Never invent quotations, page numbers, sales figures or specific passages.
  Describe the argument, not fabricated detail.
- Never invent the reader's biography or what they have read.
- Where a book's central claim is contested, say who contests it and why.
- No motivational padding, no "a must-read", no jacket-copy register.
"""

BOOK_TOOL = {
    "name": "record_book_note",
    "description": "Record the note on this book.",
    "input_schema": {
        "type": "object",
        "properties": {
            "argument": {"type": "string"},
            "one_idea": {"type": "string"},
            "verdict": {"type": "string", "description": "Worth the hours or not, and in what form."},
            "caveat": {"type": "string"},
        },
        "required": ["argument", "one_idea", "verdict", "caveat"],
        "additionalProperties": False,
    },
    "strict": True,
}

NEWS_SYSTEM = """You triage the day's money headlines for a reader learning how money works.

Most financial news is noise: price moves with a story attached afterwards,
speculation about decisions not yet made, and company results that change nothing
for anyone reading them. Your job is to find the few items with a MECHANISM worth
understanding, and to say plainly what you ignored.

Pick at most 4. Prefer, in order:
1. A decision by an institution that actually sets conditions — a central bank,
   a regulator, a tax authority.
2. Something that illustrates a mechanism the reader is learning: how credit is
   priced, how a market breaks, how an incentive plays out.
3. Something specific to Japan or the yen, which is where they earn and spend.

Actively deprioritise: daily index moves, single-company earnings without a
wider lesson, price predictions, and anything whose headline is a question.

For each pick write `why`: <= 25 words on the mechanism it shows — not a summary
of the article. Then write `ignored`: <= 30 words naming the KIND of story you
skipped and why, so the reader learns the filter rather than just the result.

If nothing clears the bar, return an empty list and say so in `ignored`. A quiet
day is a real finding, not a failure.

Hard rules:
- You have headlines and short excerpts only. Never assert detail beyond them,
  and never imply you read the full article.
- No price predictions, no advice to buy or sell anything.
"""

NEWS_TOOL = {
    "name": "record_news",
    "description": "Record the triaged headlines.",
    "input_schema": {
        "type": "object",
        "properties": {
            "picks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "The item id given in the prompt."},
                        "why": {"type": "string"},
                    },
                    "required": ["id", "why"],
                    "additionalProperties": False,
                },
            },
            "ignored": {"type": "string"},
        },
        "required": ["picks", "ignored"],
        "additionalProperties": False,
    },
    "strict": True,
}


def profile_block(cfg: Config) -> str:
    """The person, rendered for the prompt. Only fields that are filled in."""
    p = cfg.profile
    ident = p.get("identity", {}) or {}
    skills = p.get("skills", {}) or {}
    cons = p.get("constraints", {}) or {}
    prefs = p.get("preferences", {}) or {}
    lines = [
        f"Role: {ident.get('role', 'software engineer')} with a {ident.get('employment', 'full-time job')}, based in {ident.get('location', 'Tokyo')}.",
        f"Strong skills: {', '.join(skills.get('strong') or ['Python', 'backend', 'AI/ML', 'cloud'])}.",
    ]
    if skills.get("working_knowledge"):
        lines.append(f"Also knows: {', '.join(skills['working_knowledge'])}.")
    if skills.get("avoid"):
        lines.append(f"Does not want to do: {', '.join(skills['avoid'])}.")
    lines.append(
        f"Has about {cons.get('weekly_hours_available', 8)} hours a week "
        f"({cons.get('usual_slots', 'evenings and weekends')}) and "
        f"{cons.get('capital_available_jpy', 0)} JPY of spare capital."
    )
    if cons.get("cannot"):
        lines.append("Hard constraints: " + "; ".join(cons["cannot"]) + ".")
    for pat in (p.get("behaviour", {}) or {}).get("patterns", []) or []:
        # Deliberately no id: it is a YAML key, and the model echoed it into a
        # lesson as "You have present_bias and scattered_focus."
        lines.append(f"Behavioural pattern: {one_line(pat.get('description', ''), 240)}")
    if prefs.get("favour"):
        lines.append(f"More interested in: {', '.join(prefs['favour'])}.")
    if prefs.get("mute"):
        lines.append(f"Not interested in: {', '.join(prefs['mute'])}.")
    goals = p.get("goals", {}) or {}
    if goals.get("primary"):
        lines.append(f"Stated priority: {one_line(goals['primary'], 260)}")
    if goals.get("secondary"):
        lines.append(f"Secondary, not urgent: {one_line(goals['secondary'], 220)}")
    if goals.get("current_focus"):
        lines.append(f"Current focus: {goals['current_focus']}")
    return "\n".join(lines)


# --- heuristic (no API) -----------------------------------------------------

_PAYING = re.compile(r"\b(mrr|arr|revenue|paying|customers?|clients?|\$\d|¥\d|subscription|charge[ds]?|invoice)\b", re.I)
_RECURRING = re.compile(r"\b(saas|subscription|retainer|monthly|recurring|membership)\b", re.I)
_SERVICE = re.compile(r"\b(freelanc\w*|consult\w*|agency|contract\w*|audit|migration)\b", re.I)
_TECHY = re.compile(r"\b(api|python|backend|infra|cloud|aws|devops|data|ml|ai|llm|database|postgres|kubernetes|automation|script|sdk|cli)\b", re.I)
_HEAVY = re.compile(r"\b(hardware|inventory|warehouse|manufactur\w*|licen[cs]e[ds]?|regulat\w*|fund(ing|raise)|marketplace|two-sided)\b", re.I)


class HeuristicScorer:
    """Deterministic, offline, and honest about being rough."""

    name = "heuristic"

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _text(self, item: Item) -> str:
        return f"{item.title} {item.excerpt}"

    def score_streams(self, items: Sequence[Item]) -> list[StreamScore]:
        out = []
        for item in items:
            text = self._text(item)
            techy = bool(_TECHY.search(text))
            heavy = bool(_HEAVY.search(text))
            paying = bool(_PAYING.search(text))
            recurring = bool(_RECURRING.search(text))
            service = bool(_SERVICE.search(text))

            scores = {
                "skill_fit": 8 if techy and not heavy else (5 if techy else 4),
                "capital": 4 if heavy else 8,
                "time_to_first_yen": 8 if service else (6 if paying else 5),
                "proof_of_demand": 8 if paying else (6 if item.points >= 50 else 4),
                "recurring": 8 if recurring else (5 if service else 4),
                "time_cost": 7 if not heavy else 4,
            }
            rung = "1-skills" if service else ("3-product" if recurring else "2-productized")
            total = weighted_total(scores)
            out.append(
                StreamScore(
                    item=item,
                    scores=scores,
                    rung=rung,
                    opportunity=one_line(item.title, 90),
                    why_now="signal from " + item.source_name if paying else "no demand evidence in the item",
                    verdict=f"Scored offline ({total}/10) — {verdict_band(total)[1]}",
                    scored_by=self.name,
                )
            )
        return out

    def write_book_note(self, book):
        from .books import BookNote

        return BookNote(book=book, argument="", one_idea="",
                        verdict="No note yet — the offline scorer cannot judge a book.",
                        caveat="", written_by="heuristic")

    def triage_news(self, items):
        """Offline: take the highest-weighted few and say nothing about why."""
        return [(i, "") for i in items[:3]], "Headlines were not triaged — offline mode."

    def write_lesson(self, topic):
        """Offline mode cannot teach. It shows the syllabus entry and says so,
        rather than producing something that looks like a lesson and is not."""
        from .curriculum import Lesson

        return Lesson(
            topic=topic,
            body=(f"*This lesson has not been written yet — the offline scorer cannot teach. "
                  f"It will be written on the next run with a working Claude backend.*\n\n"
                  f"**Scope:** {topic.scope}"),
            key_idea=topic.scope,
            check=f"Look up the primary source for: {topic.scope}",
            hard_truth="",
            relevance="",
            written_by="heuristic",
        )

    def summarise_mind(self, item: Item) -> MindPiece:
        excerpt = clip_words(item.excerpt, 35)
        # Offline mode cannot summarise, so it must not pretend to. The feed's
        # own excerpt is shown, labelled as such, next to the link.
        summary = (
            f"*Offline mode — no summary was generated. The feed's own excerpt:* “{excerpt}”"
            if excerpt else
            "*Offline mode — no summary was generated and the feed gave no excerpt. Open the link to read it.*"
        )
        return MindPiece(
            item=item,
            summary=summary,
            key_idea=one_line(item.title, 120),
            catch="",
            summarised_by=self.name,
        )


# --- Claude ----------------------------------------------------------------


class _LLMScorer:
    """Shared prompt-building and reply-handling for both model-backed scorers.

    Subclasses implement `_call(system, user, tool) -> dict | None`; returning
    None means "this request did not produce usable JSON", and the caller
    quietly falls back to the heuristic for that batch. Keeping the batching
    and parsing here means the API and CLI backends cannot drift apart.
    """

    name = "llm"

    def _call(self, system: str, user: str, tool: dict) -> dict | None:  # pragma: no cover
        raise NotImplementedError

    def score_streams(self, items: Sequence[Item]) -> list[StreamScore]:
        results: list[StreamScore] = []
        pending = list(items)
        for start in range(0, len(pending), self.batch_size):
            batch = pending[start : start + self.batch_size]
            payload = self._call(SCORE_SYSTEM, self._stream_prompt(batch), SCORE_TOOL)
            if payload is None:
                results.extend(self.fallback.score_streams(batch))
                continue
            by_id = {str(row.get("id")): row for row in payload.get("items", [])}
            for idx, item in enumerate(batch):
                row = by_id.get(str(idx + 1))
                if not row:
                    results.extend(self.fallback.score_streams([item]))
                    continue
                scores = {k: int(max(1, min(10, row.get(k, 5)))) for k in CRITERION_KEYS}
                rung = row.get("rung") if row.get("rung") in RUNGS else "2-productized"
                results.append(
                    StreamScore(
                        item=item,
                        scores=scores,
                        rung=rung,
                        opportunity=one_line(row.get("opportunity", item.title), 140),
                        verdict=one_line(row.get("verdict", ""), 220),
                        why_now=one_line(row.get("why_now", ""), 160),
                        scored_by=self.name,
                    )
                )
        return results

    def _stream_prompt(self, batch: Sequence[Item]) -> str:
        lines = ["THE PERSON:", self.profile, "", "ITEMS TO SCORE:"]
        for idx, item in enumerate(batch, 1):
            lines.append(f"\n[{idx}] {item.title}")
            lines.append(f"    source: {item.source_name}" + (f" · {item.points} points" if item.points else ""))
            if item.excerpt:
                lines.append(f"    excerpt: {clip_words(item.excerpt, 55)}")
        lines.append("\nScore every item. Use the id numbers exactly as given.")
        return "\n".join(lines)

    def summarise_mind(self, item: Item) -> MindPiece:
        user = (
            f"THE PERSON:\n{self.profile}\n\n"
            f"ARTICLE\ntitle: {item.title}\nsource: {item.source_name}\n"
            f"excerpt: {clip_words(item.excerpt, 60) or '(the feed gave no excerpt)'}"
        )
        payload = self._call(MIND_SYSTEM, user, MIND_TOOL)
        if payload is None:
            return self.fallback.summarise_mind(item)
        return MindPiece(
            item=item,
            summary=str(payload.get("summary", "")).strip() or self.fallback.summarise_mind(item).summary,
            key_idea=one_line(payload.get("key_idea", ""), 200),
            catch=one_line(payload.get("catch", ""), 260),
            summarised_by=self.name,
        )

    def write_lesson(self, topic):
        from .curriculum import Lesson

        user = (
            f"THE READER:\n{self.profile}\n\n"
            f"LESSON\ntrack: {topic.track_name} — {topic.question}\n"
            f"title: {topic.title}\n"
            f"scope: {topic.scope}"
        )
        payload = self._call(LESSON_SYSTEM, user, LESSON_TOOL)
        if payload is None:
            return self.fallback.write_lesson(topic)
        body = str(payload.get("body", "")).strip()
        if not body:
            return self.fallback.write_lesson(topic)
        return Lesson(
            topic=topic,
            body=body,
            key_idea=one_line(payload.get("key_idea", ""), 220),
            hard_truth=one_line(payload.get("hard_truth", ""), 300),
            check=one_line(payload.get("check", ""), 300),
            relevance=one_line(payload.get("relevance", ""), 200),
            written_by=self.name,
        )

    def write_book_note(self, book):
        from .books import BookNote

        user = (
            f"THE READER:\n{self.profile}\n\n"
            f"BOOK\ntitle: {book.title}\nauthor: {book.author}\n"
            f"year: {book.year or 'unknown'}\ntrack: {book.track}"
            + (f"\nnote from the list: {book.note}" if book.note else "")
        )
        payload = self._call(BOOK_SYSTEM, user, BOOK_TOOL)
        if payload is None:
            return self.fallback.write_book_note(book)
        argument = str(payload.get("argument", "")).strip()
        if not argument:
            return self.fallback.write_book_note(book)
        return BookNote(
            book=book, argument=argument,
            one_idea=one_line(payload.get("one_idea", ""), 240),
            verdict=one_line(payload.get("verdict", ""), 320),
            caveat=one_line(payload.get("caveat", ""), 320),
            written_by=self.name,
        )

    def triage_news(self, items):
        if not items:
            return [], "No headlines were collected."
        lines = ["HEADLINES:"]
        for idx, it in enumerate(items, 1):
            lines.append(f"\n[{idx}] {it.title}")
            lines.append(f"    source: {it.source_name}")
            if it.excerpt:
                lines.append(f"    excerpt: {clip_words(it.excerpt, 40)}")
        payload = self._call(NEWS_SYSTEM, "\n".join(lines), NEWS_TOOL)
        if payload is None:
            return self.fallback.triage_news(items)
        picked = []
        for row in payload.get("picks", [])[:4]:
            try:
                item = items[int(str(row.get("id")).strip()) - 1]
            except (ValueError, IndexError, TypeError):
                continue
            picked.append((item, one_line(row.get("why", ""), 200)))
        return picked, one_line(payload.get("ignored", ""), 220)

    def close(self) -> None:
        pass


class ClaudeScorer(_LLMScorer):
    """Haiku 4.5 with forced tool use, so every response is schema-valid.

    Falls back to the heuristic, per item, on any API problem — a bad API day
    degrades the brief, it never cancels it.
    """

    name = "claude"

    def __init__(self, cfg: Config, usage: UsageStore):
        import anthropic  # imported lazily so --no-llm needs no SDK at all

        self.cfg = cfg
        self.usage = usage
        self.fallback = HeuristicScorer(cfg)
        self.model = cfg.get("model.scorer", "claude-haiku-4-5")
        self.max_tokens = int(cfg.get("model.max_output_tokens", 2000))
        self.temperature = float(cfg.get("model.temperature", 0.2))
        self.batch_size = int(cfg.get("model.batch_size", 8))
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.profile = profile_block(cfg)
        self.degraded: list[str] = []

    def _call(self, system: str, user: str, tool: dict) -> dict | None:
        stop = self.usage.exhausted()
        if stop:
            self.degraded.append(f"budget stop: {stop}")
            return None
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[{"role": "user", "content": user}],
            )
        except self._anthropic.RateLimitError:
            self.degraded.append("rate limited by the API")
            return None
        except self._anthropic.APIStatusError as exc:
            self.degraded.append(f"API error {exc.status_code}")
            return None
        except self._anthropic.APIConnectionError:
            self.degraded.append("could not reach the API")
            return None
        except Exception as exc:  # never let scoring end the run
            self.degraded.append(f"{type(exc).__name__}")
            log.warning("scorer call failed: %s", exc)
            return None

        self.usage.record(resp.usage.input_tokens, resp.usage.output_tokens)
        for block in resp.content:
            if block.type == "tool_use":
                # Inputs are JSON-parsed by the SDK; never string-match them.
                return dict(block.input)
        self.degraded.append("model returned no tool call")
        return None



class ClaudeCodeScorer(_LLMScorer):
    """Scores through the Claude Code CLI — no API key, billed to the subscription.

    Same interface and the same failure posture as ClaudeScorer: any batch that
    errors or comes back unparseable falls through to the heuristic, and the
    brief records which scorer actually produced it.
    """

    name = "claude-code"

    def __init__(self, cfg: Config, usage: UsageStore):
        from .claude_cli import ClaudeCodeClient, ClaudeCodeError, describe_schema

        self.cfg = cfg
        self.usage = usage
        self.fallback = HeuristicScorer(cfg)
        self.batch_size = int(cfg.get("model.batch_size", 8))
        self.profile = profile_block(cfg)
        self.degraded: list[str] = []
        self._error = ClaudeCodeError
        self._describe = describe_schema
        self.client = ClaudeCodeClient(
            model=cfg.get("model.cli_model", "haiku"),
            timeout=int(cfg.get("model.cli_timeout_seconds", 420)),
        )
        # A subscription run is not billed per call, so the dollar ceiling would
        # trip on a price nobody pays. The call ceiling is the real guard.
        usage.billed = False

    def _schema_prompt(self, tool: dict) -> str:
        return (
            "Reply with ONE JSON object and nothing else — no prose, no code fence.\n"
            "Keys:\n" + self._describe(tool["input_schema"])
        )

    def _call(self, system: str, user: str, tool: dict) -> dict | None:
        stop = self.usage.exhausted()
        if stop:
            self.degraded.append(f"budget stop: {stop}")
            return None
        full_system = system + "\n\n" + self._schema_prompt(tool)
        for attempt in (1, 2):
            try:
                payload, stats = self.client.ask(full_system, user)
                self.usage.record(stats["input_tokens"], stats["output_tokens"],
                                  equivalent_usd=stats["equivalent_usd"])
                return payload
            except self._error as exc:
                message = str(exc)
                if attempt == 1 and ("JSON" in message or "reply" in message):
                    # One retry, with the instruction made blunter.
                    user = user + "\n\nReturn ONLY the JSON object. No explanation."
                    continue
                self.degraded.append(message[:80])
                log.warning("claude-code scorer: %s", message)
                return None
        return None

    def close(self) -> None:
        self.client.close()


def _has_api_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def build_scorer(cfg: Config, usage: UsageStore, use_llm: bool = True):
    """Pick a scoring backend.

    model.backend in settings.yaml:
      claude-code  the Claude Code CLI — no API key, billed to a Claude
                   subscription. Needs an interactive login or, in CI, a
                   CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`.
      api          the Anthropic API, needs ANTHROPIC_API_KEY.
      offline      the deterministic heuristic scorer; no network.
      auto         claude-code if the CLI is there, else api if a key is there,
                   else offline.

    Whatever is chosen, an unavailable backend degrades to the next one rather
    than failing the run, and the brief names the scorer that actually ran.
    """
    from .claude_cli import cli_available

    if not use_llm:
        return HeuristicScorer(cfg)

    backend = str(os.getenv("LUMINA_BACKEND") or cfg.get("model.backend", "auto")).lower()
    if backend == "auto":
        backend = "claude-code" if cli_available() else ("api" if _has_api_key() else "offline")

    if backend == "offline":
        return HeuristicScorer(cfg)

    if backend == "claude-code":
        if not cli_available():
            from .claude_cli import auth_hint
            log.warning("model.backend is claude-code but the CLI is not installed — "
                        "install it with `npm i -g @anthropic-ai/claude-code`. %s", auth_hint())
            return ClaudeScorer(cfg, usage) if _has_api_key() else HeuristicScorer(cfg)
        try:
            return ClaudeCodeScorer(cfg, usage)
        except Exception as exc:
            log.warning("could not start the Claude Code scorer (%s) — falling back", exc)
            return ClaudeScorer(cfg, usage) if _has_api_key() else HeuristicScorer(cfg)

    if backend == "api":
        if not _has_api_key():
            log.warning("model.backend is api but no ANTHROPIC_API_KEY is set — scoring offline")
            return HeuristicScorer(cfg)
        try:
            return ClaudeScorer(cfg, usage)
        except Exception as exc:
            log.warning("could not start the Claude API scorer (%s) — falling back to heuristic", exc)
            return HeuristicScorer(cfg)

    log.warning("unknown model.backend %r — scoring offline", backend)
    return HeuristicScorer(cfg)
