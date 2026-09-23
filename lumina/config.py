"""Configuration loading. Everything tunable lives in config/*.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .util import ROOT, log


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"missing config file: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _dig(data: dict, dotted: str, default: Any = None) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


@dataclass
class Source:
    id: str
    name: str
    kind: str
    url: str
    section: str
    enabled: bool = True
    backfill: bool = False
    auth: str = "none"
    weight: float = 1.0
    params: dict = field(default_factory=dict)
    notes: str = ""
    disabled_reason: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "Source":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})


@dataclass
class Config:
    settings: dict
    profile: dict
    sources: list[Source]
    root: Path = ROOT

    # --- paths (single place, so tests can point them elsewhere) ---
    @property
    def daily_dir(self) -> Path:
        return self.root / "daily"

    @property
    def digest_dir(self) -> Path:
        return self.root / "digests"

    @property
    def inbox_dir(self) -> Path:
        return self.root / "ideas" / "inbox"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def streams_dir(self) -> Path:
        return self.root / "streams"

    @property
    def template_dir(self) -> Path:
        return self.root / "templates"

    @property
    def principles_file(self) -> Path:
        return self.root / "curriculum" / "principles.md"

    @property
    def active_stream_file(self) -> Path:
        return self.streams_dir / "active.md"

    def get(self, dotted: str, default: Any = None) -> Any:
        return _dig(self.settings, dotted, default)

    def profile_get(self, dotted: str, default: Any = None) -> Any:
        return _dig(self.profile, dotted, default)

    # --- convenience ---
    def enabled_sources(self, section: str | None = None) -> list[Source]:
        out = [s for s in self.sources if s.enabled]
        if section:
            out = [s for s in out if s.section == section]
        return out

    def backfill_sources(self, section: str | None = None) -> list[Source]:
        return [s for s in self.enabled_sources(section) if s.backfill]

    def disabled_sources(self) -> list[Source]:
        return [s for s in self.sources if not s.enabled]

    def source(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.id == source_id), None)


def load_config(root: Path | str = ROOT) -> Config:
    root = Path(root)
    cfg_dir = root / "config"
    settings = _load_yaml(cfg_dir / "settings.yaml")
    profile = _load_yaml(cfg_dir / "profile.yaml")
    raw_sources = _load_yaml(cfg_dir / "sources.yaml")

    sources: list[Source] = []
    for group, entries in (raw_sources or {}).items():
        for entry in entries or []:
            entry.setdefault("section", group)
            try:
                sources.append(Source.from_dict(entry))
            except TypeError as exc:
                log.warning("skipping malformed source %r: %s", entry.get("id"), exc)

    seen_ids = set()
    for s in sources:
        if s.id in seen_ids:
            raise ValueError(f"duplicate source id in sources.yaml: {s.id}")
        seen_ids.add(s.id)

    return Config(settings=settings, profile=profile, sources=sources, root=root)
