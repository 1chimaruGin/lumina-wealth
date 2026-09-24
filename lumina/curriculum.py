"""The syllabus: what to teach next, and the lessons it produces.

Feeds tell you what happened this week. A syllabus teaches you something in
sequence, never runs dry, and can start in 3000 BC — which is why it is the
spine of the Mind section and the feeds are the supplement.

Lessons are generated once and cached in curriculum/lessons/. A rebuild of an
old brief re-reads the file rather than paying to write it again, so rebuilding
history is free and produces exactly the same lesson.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from .util import log, read_json, slugify, write_json, write_text


@dataclass
class Topic:
    id: str
    title: str
    scope: str
    track: str
    track_name: str
    question: str
    position: int

    @property
    def slug(self) -> str:
        return f"{self.id}-{slugify(self.title, 48)}"


@dataclass
class Track:
    key: str
    name: str
    question: str
    blurb: str
    topics: list[Topic] = field(default_factory=list)


@dataclass
class Syllabus:
    tracks: dict[str, Track]
    rotation: dict[int, str | None]

    def topic(self, topic_id: str) -> Topic | None:
        for tr in self.tracks.values():
            for t in tr.topics:
                if t.id == topic_id:
                    return t
        return None

    @property
    def all_topics(self) -> list[Topic]:
        return [t for tr in self.tracks.values() for t in tr.topics]

    def track_for(self, day: date) -> str | None:
        return self.rotation.get(day.weekday())


def load_syllabus(path: Path | str) -> Syllabus:
    path = Path(path)
    if not path.exists():
        return Syllabus(tracks={}, rotation={})
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rotation = {int(k): v for k, v in (raw.get("meta", {}).get("rotation", {}) or {}).items()}
    tracks: dict[str, Track] = {}
    for key, spec in (raw.get("tracks") or {}).items():
        track = Track(key=key, name=spec.get("name", key.title()),
                      question=spec.get("question", ""), blurb=(spec.get("blurb") or "").strip())
        for i, t in enumerate(spec.get("topics") or []):
            track.topics.append(Topic(
                id=t["id"], title=t["title"], scope=t.get("scope", ""),
                track=key, track_name=track.name, question=track.question, position=i,
            ))
        tracks[key] = track
    return Syllabus(tracks=tracks, rotation=rotation)


# --- progress ---------------------------------------------------------------


@dataclass
class CurriculumState:
    path: Path
    taught: dict          # topic_id -> ISO date first taught

    @classmethod
    def load(cls, data_dir: Path) -> "CurriculumState":
        path = Path(data_dir) / "curriculum.json"
        raw = read_json(path, default={"taught": {}}) or {}
        return cls(path=path, taught=raw.get("taught", {}))

    def is_taught(self, topic_id: str) -> bool:
        return topic_id in self.taught

    def mark(self, topic_id: str, on: date) -> None:
        existing = self.taught.get(topic_id)
        if not existing or str(on) < existing:
            self.taught[topic_id] = str(on)

    def forget_on(self, d: date | str) -> int:
        """Drop entries for exactly this day.

        Rebuilding ONE old day must not disturb the days after it — which is
        what forget_since would do, since it drops everything from that date
        onward.
        """
        day = str(d)
        stale = [k for k, v in self.taught.items() if str(v) == day]
        for k in stale:
            del self.taught[k]
        return len(stale)

    def forget_since(self, d: date | str) -> int:
        """Rebuilding a date must replay the same lessons, not skip ahead."""
        cutoff = str(d)
        stale = [k for k, v in self.taught.items() if str(v) >= cutoff]
        for k in stale:
            del self.taught[k]
        return len(stale)

    def taught_by_track(self, syllabus: Syllabus) -> dict[str, int]:
        counts = {k: 0 for k in syllabus.tracks}
        for tid in self.taught:
            topic = syllabus.topic(tid)
            if topic:
                counts[topic.track] = counts.get(topic.track, 0) + 1
        return counts

    def save(self) -> None:
        write_json(self.path, {"taught": self.taught, "count": len(self.taught)})


def next_topics(syllabus: Syllabus, state: CurriculumState, day: date, count: int = 2) -> list[Topic]:
    """Pick the day's lessons.

    The first comes from the weekday's track, so each day has a theme. The rest
    come from whichever track is furthest behind, which keeps coverage even
    without anyone having to manage it — otherwise the tracks that happen to
    fall on busy weekdays quietly fall behind forever.
    """
    if not syllabus.tracks:
        return []

    def untaught(track_key: str) -> list[Topic]:
        track = syllabus.tracks.get(track_key)
        return [t for t in (track.topics if track else []) if not state.is_taught(t.id)]

    picked: list[Topic] = []
    chosen_ids: set[str] = set()

    primary = syllabus.track_for(day)
    if primary and untaught(primary):
        first = untaught(primary)[0]
        picked.append(first)
        chosen_ids.add(first.id)

    counts = state.taught_by_track(syllabus)
    while len(picked) < count:
        # Behind = fewest taught, then largest remaining, so an exhausted track
        # never blocks the rotation.
        candidates = [
            (counts.get(k, 0), -len(untaught(k)), k)
            for k in syllabus.tracks
            if [t for t in untaught(k) if t.id not in chosen_ids]
        ]
        if not candidates:
            break
        candidates.sort()
        track_key = candidates[0][2]
        nxt = next(t for t in untaught(track_key) if t.id not in chosen_ids)
        picked.append(nxt)
        chosen_ids.add(nxt.id)
        counts[track_key] = counts.get(track_key, 0) + 1

    return picked


# --- lessons ----------------------------------------------------------------


@dataclass
class Lesson:
    topic: Topic
    body: str
    key_idea: str
    reflection: str
    relevance: str = ""
    written_by: str = "heuristic"

    @property
    def is_placeholder(self) -> bool:
        return self.written_by == "heuristic"


_LESSON_RE = re.compile(
    r"^---\s*\n(?P<fm>.*?)\n---\s*\n(?P<body>.*)$", re.S
)


def lesson_path(root: Path, topic: Topic) -> Path:
    return Path(root) / "curriculum" / "lessons" / f"{topic.slug}.md"


def load_lesson(root: Path, topic: Topic) -> Lesson | None:
    """Read a previously written lesson. Caching is what makes rebuilding a
    past brief free and deterministic."""
    path = lesson_path(root, topic)
    if not path.exists():
        return None
    m = _LESSON_RE.match(path.read_text(encoding="utf-8"))
    if not m:
        return None
    meta = yaml.safe_load(m.group("fm")) or {}
    body = m.group("body")
    # Strip the rendered heading and the trailing blocks we add on save.
    body = re.sub(r"^#\s+.*?\n+", "", body, count=1)
    body = re.split(r"\n\*\*Key idea\.\*\*", body)[0].strip()
    return Lesson(
        topic=topic,
        body=body,
        key_idea=meta.get("key_idea", ""),
        reflection=meta.get("reflection", ""),
        relevance=meta.get("relevance", ""),
        written_by=meta.get("written_by", "heuristic"),
    )


def save_lesson(root: Path, lesson: Lesson) -> Path:
    t = lesson.topic
    meta = {
        "id": t.id,
        "title": t.title,
        "track": t.track,
        "track_name": t.track_name,
        "scope": t.scope,
        "key_idea": lesson.key_idea,
        "reflection": lesson.reflection,
        "relevance": lesson.relevance,
        "written_by": lesson.written_by,
    }
    fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip()
    doc = f"""---
{fm}
---

# {t.title}

{lesson.body}

**Key idea.** {lesson.key_idea}

**Ask yourself:** {lesson.reflection}
"""
    return write_text(lesson_path(root, lesson.topic), doc)


def get_or_write_lesson(root: Path, topic: Topic, writer) -> Lesson:
    """Cached generation. `writer` is any scorer exposing write_lesson()."""
    cached = load_lesson(root, topic)
    if cached and not cached.is_placeholder:
        return cached
    lesson = writer.write_lesson(topic)
    if not lesson.is_placeholder:
        save_lesson(root, lesson)
    elif cached:
        return cached
    return lesson
