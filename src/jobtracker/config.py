"""Load config.toml into a typed, frozen Config."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass(frozen=True)
class Config:
    backfill_days: int
    overlap_days: int
    ghost_days: int
    confidence_threshold: float
    ollama_host: str
    ollama_model: str
    db_path: Path
    credentials_path: Path
    token_path: Path
    categories: tuple[str, ...]
    company_aliases: dict[str, str]
    ats_domains: tuple[str, ...]
    subject_keywords: tuple[str, ...]
    body_keywords: tuple[str, ...]
    noise_senders: tuple[str, ...]
    noise_subject_patterns: tuple[str, ...]


def load_config(path: str | Path = "config.toml") -> Config:
    cfg_path = Path(path)
    data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    root = cfg_path.resolve().parent
    paths = data.get("paths", {})
    pre = data["prefilter"]
    aliases = {k.lower(): v.lower() for k, v in data.get("company_aliases", {}).items()}
    return Config(
        backfill_days=data["sync"]["backfill_days"],
        overlap_days=data["sync"]["overlap_days"],
        ghost_days=data["ghosting"]["ghost_days"],
        confidence_threshold=data["review"]["confidence_threshold"],
        ollama_host=data["ollama"]["host"],
        ollama_model=data["ollama"]["model"],
        db_path=root / paths.get("db", "data/tracker.db"),
        credentials_path=root / paths.get("credentials", "credentials.json"),
        token_path=root / paths.get("token", "token.json"),
        categories=tuple(data["categories"]["names"]),
        company_aliases=aliases,
        ats_domains=tuple(pre["ats_domains"]),
        subject_keywords=tuple(pre["subject_keywords"]),
        body_keywords=tuple(pre["body_keywords"]),
        noise_senders=tuple(pre["noise_senders"]),
        noise_subject_patterns=tuple(pre["noise_subject_patterns"]),
    )
