"""LLM classification behind a minimal provider interface.

v1 wires exactly one provider (local Ollama). To add a cloud provider
later, implement `classify(EmailMessage) -> Extraction` and swap it in
cli.py — nothing else changes.
"""

from __future__ import annotations

from typing import Protocol

import ollama
from pydantic import ValidationError

from jobtracker.models import EmailMessage, Extraction

MAX_BODY_CHARS = 4000

SYSTEM_PROMPT = """\
You classify emails for a personal job-application tracker. The user applies
to software/cloud engineering jobs. Given one email, return JSON matching the
provided schema. Field meanings:

relevance:
- my_application: concerns a job application the user submitted — including
  received/thank-you-for-applying confirmations, status updates ("update on
  your application"), and rejections. These stay my_application even when sent
  by a staffing agency (e.g. TEKsystems, Insight Global) or an ATS on the
  employer's behalf.
- inbound_lead: a recruiter or company reaching out about a job the user did
  NOT apply to. Only use this when the email is unsolicited outreach; anything
  referencing an application the user made is my_application.
- not_job_related: everything else (newsletters, alerts, receipts, personal mail)

status_signal — what THIS email indicates for the application:
- applied: confirmation an application was received ("thanks for applying")
- recruiter_screen: invite or scheduling for a recruiter/HR phone screen
- assessment: online assessment, coding challenge, or take-home
- interview: technical or hiring-manager interview
- onsite_final: final round, onsite, or superday
- offer: an offer is extended
- rejected: explicit rejection ("we will not be moving forward", "position has been filled")
- withdrawn: the user withdrew their application
- other: status-neutral (e.g. "we're still reviewing", a request to send more information)

A stage signal (recruiter_screen and beyond) requires that THIS email contains
a scheduling link, a proposed or confirmed date/time, or a direct request to
book a specific meeting. Anything conditional or hypothetical — "if your
skills match…", "if your qualifications match our needs, you may be contacted
to schedule a screening call" — does NOT advance the stage: use applied (for
application confirmations) or other.

email_kind:
- auto_confirmation: automated "application received" template
- automated_notice: any other automated/templated notice, including template rejections
- human_reply: written by a real person specifically to the user
- scheduling: interview scheduling or calendar coordination
- other: none of the above

company: the employer's name (not the ATS vendor). role_title: the job title as
written, including any requisition codes; use "" when the email names no job
title — never invent one and never use a process phrase like "Virtual
Interview". category: pick the closest from {categories}. confidence: 0.0-1.0
for this whole extraction. reason: one short sentence. Return only JSON.
"""


class Classifier(Protocol):
    def classify(self, email: EmailMessage) -> Extraction: ...


def _format_schema() -> dict:
    """Extraction's schema with every field required. The pydantic defaults
    make fields optional, and under constrained decoding the model then omits
    company/role_title entirely — silently backfilled as empty strings."""
    schema = Extraction.model_json_schema()
    return {**schema, "required": list(schema["properties"])}


FORMAT_SCHEMA = _format_schema()


class OllamaClassifier:
    def __init__(self, host: str, model: str, categories: tuple[str, ...]):
        self._client = ollama.Client(host=host)
        self._model = model
        self._system = SYSTEM_PROMPT.format(categories=", ".join(categories))

    def classify(self, email: EmailMessage) -> Extraction:
        user = (
            f"From: {email.sender}\n"
            f"Subject: {email.subject}\n"
            f"Date: {email.date.isoformat()}\n\n"
            f"{email.body[:MAX_BODY_CHARS]}"
        )
        messages = [
            {"role": "system", "content": self._system},
            {"role": "user", "content": user},
        ]
        for attempt in range(2):
            response = self._client.chat(
                model=self._model,
                messages=messages,
                format=FORMAT_SCHEMA,
                options={"temperature": 0},
            )
            content = response["message"]["content"]
            try:
                return Extraction.model_validate_json(content)
            except ValidationError:
                if attempt == 0:
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": "That was not valid JSON for the schema. "
                            "Return only valid JSON.",
                        }
                    )
        return Extraction(
            relevance="unknown", confidence=0.0, reason="model output failed schema validation"
        )
