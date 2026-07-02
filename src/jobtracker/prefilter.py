"""Cheap header-level filter that gates the expensive LLM call.

Exclusions win over inclusions: a job-alert digest full of the word
"application" must still be dropped before it reaches the classifier.
"""

from __future__ import annotations

import re

from jobtracker.config import Config
from jobtracker.models import EmailMessage

_ADDR = re.compile(r"<([^>]+)>")

CANDIDATE = "candidate"


def sender_domain(sender: str) -> str:
    m = _ADDR.search(sender)
    addr = m.group(1) if m else sender
    _, _, domain = addr.strip().lower().rpartition("@")
    return domain


def check(email: EmailMessage, cfg: Config) -> str:
    """Return 'candidate' or a skip reason ('noise_sender', 'noise_subject',
    'no_match'). Works on headers + snippet so it can run on a metadata-only
    fetch, before the full body is downloaded."""
    sender = email.sender.lower()
    subject = email.subject.lower()
    text = f"{email.snippet} {email.body}"[:2000].lower()

    if any(noise in sender for noise in cfg.noise_senders):
        return "noise_sender"
    if any(pattern in subject for pattern in cfg.noise_subject_patterns):
        return "noise_subject"

    domain = sender_domain(email.sender)
    if any(domain == d or domain.endswith("." + d) for d in cfg.ats_domains):
        return CANDIDATE
    if any(keyword in subject for keyword in cfg.subject_keywords):
        return CANDIDATE
    if any(keyword in text for keyword in cfg.body_keywords):
        return CANDIDATE
    return "no_match"
