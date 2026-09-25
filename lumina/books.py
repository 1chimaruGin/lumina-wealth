"""One book a day, with an honest verdict on whether it is worth the hours.

Most money books are one idea and two hundred pages of padding. A note that
says so — and names the chapter worth reading — is worth more than a review.

Notes are generated once and cached in curriculum/notes/, so a rebuild costs
nothing and reproduces the same note.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from .util import read_json, slugify, write_json, write_text


@dataclass
class Book:
    id: str
    title: str
    author: str
    year: int | None = None
    track: str = ""
    weight: float = 1.0
    note: str = ""

    @property
    def slug(self) -> str:
        return f"{self.id}-{slugify(self.title, 44)}"

    @property
    def label(self) -> str:
        return f"{self.title} — {self.author}" + (f" ({self.year})" if self.year else "")


@dataclass
class BookNote:
    book: Book
    argument: str
    one_idea: str
    verdict: str
    caveat: str = ""
    written_by: str = "heuristic"

    @property
    def is_placeholder(self) -> bool:
        return self.written_by == "heuristic"


def load_books(path: Path | str) -> list[Book]:
    path = Path(path)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for b in raw.get("books") or []:
        out.append(Book(id=b["id"], title=b["title"], author=b.get("author", ""),
                        year=b.get("year"), track=b.get("track", ""),
                        weight=float(b.get("weight", 1.0)), note=b.get("note", "")))
    return out


@dataclass
class BookState:
    path: Path
    read: dict          # book id -> ISO date first surfaced

    @classmethod
    def load(cls, data_dir: Path) -> "BookState":
        path = Path(data_dir) / "books.json"
        raw = read_json(path, default={"read": {}}) or {}
        return cls(path=path, read=raw.get("read", {}))

    def mark(self, book_id: str, on: date) -> None:
        existing = self.read.get(book_id)
        if not existing or str(on) < existing:
            self.read[book_id] = str(on)

    def forget_on(self, d: date | str) -> int:
        day = str(d)
        stale = [k for k, v in self.read.items() if str(v) == day]
        for k in stale:
            del self.read[k]
        return len(stale)

    def forget_since(self, d: date | str) -> int:
        cutoff = str(d)
        stale = [k for k, v in self.read.items() if str(v) >= cutoff]
        for k in stale:
            del self.read[k]
        return len(stale)

    def save(self) -> None:
        write_json(self.path, {"read": self.read, "count": len(self.read)})


def next_book(books: list[Book], state: BookState, day: date, prefer_track: str = "") -> Book | None:
    """Prefer an unread book from the day's track, then any unread by weight.

    Once every book has been surfaced it starts again from the longest ago,
    which is a feature: rereading a good book beats a first pass at a bad one.
    """
    unread = [b for b in books if b.id not in state.read]
    if unread:
        pool = [b for b in unread if b.track == prefer_track] or unread
        return sorted(pool, key=lambda b: (-b.weight, b.id))[0]
    if not books:
        return None
    return sorted(books, key=lambda b: (state.read.get(b.id, ""), b.id))[0]


_FM = re.compile(r"^---\s*\n(?P<fm>.*?)\n---\s*\n(?P<body>.*)$", re.S)


def note_path(root: Path, book: Book) -> Path:
    return Path(root) / "curriculum" / "notes" / f"{book.slug}.md"


def load_note(root: Path, book: Book) -> BookNote | None:
    path = note_path(root, book)
    if not path.exists():
        return None
    m = _FM.match(path.read_text(encoding="utf-8"))
    if not m:
        return None
    meta = yaml.safe_load(m.group("fm")) or {}
    return BookNote(
        book=book,
        argument=meta.get("argument", ""),
        one_idea=meta.get("one_idea", ""),
        verdict=meta.get("verdict", ""),
        caveat=meta.get("caveat", ""),
        written_by=meta.get("written_by", "heuristic"),
    )


def save_note(root: Path, note: BookNote) -> Path:
    b = note.book
    meta = {"id": b.id, "title": b.title, "author": b.author, "year": b.year,
            "track": b.track, "argument": note.argument, "one_idea": note.one_idea,
            "verdict": note.verdict, "caveat": note.caveat, "written_by": note.written_by}
    fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip()
    doc = f"""---
{fm}
---

# {b.title}

*{b.author}{f", {b.year}" if b.year else ""}*

{note.argument}

**The one idea.** {note.one_idea}

**Verdict.** {note.verdict}

{f"**Caveat.** {note.caveat}" if note.caveat else ""}
"""
    return write_text(note_path(root, b), doc)


def get_or_write_note(root: Path, book: Book, writer) -> BookNote:
    cached = load_note(root, book)
    if cached and not cached.is_placeholder:
        return cached
    note = writer.write_book_note(book)
    if not note.is_placeholder:
        save_note(root, note)
    elif cached:
        return cached
    return note
