"""Classification: mind vs streams.

Deliberately not an LLM call. Every source declares its section in sources.yaml,
which is free, deterministic, and right ~always. The only real work is the
mixed sources (Hacker News carries both), where a keyword pass reassigns the
occasional money-psychology piece into Mind.
"""

from __future__ import annotations

import re
from typing import Iterable

from .collect import Item

# Mind = how I think and behave with money.
_MIND_PATTERNS = re.compile(
    r"\b(psychology|behaviou?r\w*|habit|discipline|mindset|money mindset|"
    r"frugal\w*|spending|saving|compound\w*|wealth|net worth|financial independence|"
    r"fire movement|retire\w*|greed|envy|patience|risk toleran\w*|loss aversion|"
    r"cognitive bias|decision[- ]making|delayed gratification|lifestyle creep)\b",
    re.I,
)

# Streams = someone is making money, or wants to.
_STREAM_PATTERNS = re.compile(
    r"\b(side project|side hustle|indie hacker|bootstrap\w*|solopreneur|"
    r"freelanc\w*|consult\w*|client|mrr|arr|saas|micro[- ]saas|productiz\w*|"
    r"launch\w*|revenue|paying customers?|first (sale|customer|dollar|client)|"
    r"pricing|monetis\w*|monetiz\w*|acquir\w*|built .* in a weekend)\b",
    re.I,
)

# Junk, not subject matter. Crypto and FX used to be listed here from when they
# were out of scope; they are now taught tracks, and leaving them in silently
# discarded every item from the crypto news source. What remains is the
# promise-of-easy-money register, which is noise in any asset class.
_NOISE_PATTERNS = re.compile(
    r"\b(get rich quick|make money fast|guaranteed returns?|risk[- ]free profit|"
    r"mlm|multi[- ]level marketing|dropship\w* course|signal group|"
    r"trading course|copy ?trading service|pump and dump)\b",
    re.I,
)


def _text_of(item: Item) -> str:
    return f"{item.title} {item.excerpt}"


def is_noise(item: Item) -> bool:
    return bool(_NOISE_PATTERNS.search(_text_of(item)))


def classify(item: Item) -> str:
    """Return 'mind' or 'streams'. The source's declared section wins unless the
    source is mixed and the text clearly points the other way."""
    text = _text_of(item)
    mind_hits = len(_MIND_PATTERNS.findall(text))
    stream_hits = len(_STREAM_PATTERNS.findall(text))

    if item.source_id.startswith("hn_"):
        # HN is the one genuinely mixed source.
        if mind_hits >= 2 and mind_hits > stream_hits:
            return "mind"
        return "streams"

    if item.section == "mind" and stream_hits >= 3 and stream_hits > mind_hits * 2:
        return "streams"
    return item.section


def classify_all(items: Iterable[Item], drop_noise: bool = True,
                 keep_sections: set[str] | None = None) -> list[Item]:
    """keep_sections are passed through untouched — news is already correctly
    sectioned by its source and must not be re-sorted into mind or streams by
    keyword matching."""
    keep = keep_sections or set()
    out = []
    for item in items:
        if drop_noise and is_noise(item):
            continue
        if item.section not in keep:
            item.section = classify(item)
        out.append(item)
    return out


def prefilter(items: Iterable[Item], section: str, limit: int) -> list[Item]:
    """Cheap local ranking before anything is sent to the API.

    Exists purely for cost: scoring 290 items with an LLM would be absurd, so a
    heuristic picks the plausible ones and the model only judges those.
    """
    pool = [i for i in items if i.section == section]

    def rank(item: Item) -> tuple:
        text = _text_of(item)
        signal = len(_STREAM_PATTERNS.findall(text)) if section == "streams" else len(_MIND_PATTERNS.findall(text))
        engagement = item.points + item.comments * 2
        recency = item.published.timestamp() if item.published else 0
        return (signal * 3 + min(engagement, 60) / 10) * item.weight, recency

    return sorted(pool, key=rank, reverse=True)[:limit]
