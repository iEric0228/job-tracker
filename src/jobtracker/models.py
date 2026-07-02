"""Shared data types: raw email container and the LLM extraction schema."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

STAGES = ["applied", "recruiter_screen", "assessment", "interview", "onsite_final", "offer"]
STAGE_RANK = {name: rank for rank, name in enumerate(STAGES, start=1)}
TERMINAL_SIGNALS = {"rejected", "offer", "withdrawn"}

Relevance = Literal["my_application", "inbound_lead", "not_job_related", "unknown"]
StatusSignal = Literal[
    "applied",
    "recruiter_screen",
    "assessment",
    "interview",
    "onsite_final",
    "offer",
    "rejected",
    "withdrawn",
    "other",
]
EmailKind = Literal["auto_confirmation", "automated_notice", "human_reply", "scheduling", "other"]


@dataclass
class EmailMessage:
    """One email as fetched from the mailbox. message_id is the provider's
    stable id and serves as the idempotency key everywhere."""

    message_id: str
    thread_id: str
    sender: str
    subject: str
    date: datetime
    body: str = ""
    snippet: str = ""


class Extraction(BaseModel):
    """Structured output the classifier must produce for one email.

    There is deliberately no event_date field: the email's Date header is
    authoritative, so the LLM is never asked for it.
    """

    relevance: Relevance = "unknown"
    company: str = ""
    role_title: str = ""
    category: str = "Other"
    status_signal: StatusSignal = "other"
    email_kind: EmailKind = "other"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
