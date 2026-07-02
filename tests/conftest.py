from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from jobtracker import db as dbmod
from jobtracker.config import Config, load_config
from jobtracker.models import EmailMessage, Extraction

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[1]


def load_fixture(name: str) -> EmailMessage:
    raw = (FIXTURES / name).read_text(encoding="utf-8")
    head, _, body = raw.partition("\n\n")
    headers: dict[str, str] = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip()
    body = body.strip()
    return EmailMessage(
        message_id=headers["message-id"],
        thread_id=headers["thread-id"],
        sender=headers["from"],
        subject=headers["subject"],
        date=datetime.fromisoformat(headers["date"]),
        body=body,
        snippet=body[:120],
    )


def all_fixtures() -> list[EmailMessage]:
    return [load_fixture(p.name) for p in sorted(FIXTURES.glob("*.txt"))]


@pytest.fixture
def cfg() -> Config:
    return load_config(REPO_ROOT / "config.toml")


@pytest.fixture
def conn():
    c = dbmod.connect(":memory:")
    yield c
    c.close()


class FakeGmail:
    """Stands in for GmailClient; serves fixture emails."""

    def __init__(self, emails: list[EmailMessage]):
        self._emails = {e.message_id: e for e in emails}

    def list_message_ids(self, after_epoch: int) -> list[str]:
        return [e.message_id for e in self._emails.values() if e.date.timestamp() >= after_epoch]

    def get_metadata(self, message_id: str) -> EmailMessage:
        e = self._emails[message_id]
        return EmailMessage(
            message_id=e.message_id,
            thread_id=e.thread_id,
            sender=e.sender,
            subject=e.subject,
            date=e.date,
            body="",
            snippet=e.snippet,
        )

    def get_full(self, message_id: str) -> EmailMessage:
        return self._emails[message_id]


class FakeClassifier:
    """Deterministic classifier keyed by message id; records every call."""

    def __init__(self, mapping: dict[str, Extraction]):
        self.mapping = mapping
        self.calls: list[str] = []

    def classify(self, email: EmailMessage) -> Extraction:
        self.calls.append(email.message_id)
        default = Extraction(relevance="not_job_related", confidence=0.9)
        return self.mapping.get(email.message_id, default).model_copy(deep=True)
