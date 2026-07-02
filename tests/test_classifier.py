from __future__ import annotations

import json

from conftest import load_fixture
from jobtracker.classifier import OllamaClassifier

VALID = json.dumps(
    {
        "relevance": "my_application",
        "company": "Acme Cloud",
        "role_title": "Cloud Support Engineer",
        "category": "Cloud Support",
        "status_signal": "applied",
        "email_kind": "auto_confirmation",
        "confidence": 0.93,
        "reason": "application confirmation",
    }
)


class FakeOllamaClient:
    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return {"message": {"content": self.replies.pop(0)}}


def make_classifier(replies: list[str]) -> tuple[OllamaClassifier, FakeOllamaClient]:
    clf = OllamaClassifier("http://localhost:11434", "test-model", ("Cloud Support", "Other"))
    fake = FakeOllamaClient(replies)
    clf._client = fake
    return clf, fake


def test_valid_output_parses():
    clf, fake = make_classifier([VALID])
    ext = clf.classify(load_fixture("greenhouse_applied.txt"))
    assert ext.relevance == "my_application"
    assert ext.status_signal == "applied"
    assert ext.confidence == 0.93
    # Structured output: the JSON schema is passed to Ollama.
    assert "properties" in fake.calls[0]["format"]
    assert fake.calls[0]["options"] == {"temperature": 0}


def test_retries_once_on_invalid_json():
    clf, fake = make_classifier(["not json at all", VALID])
    ext = clf.classify(load_fixture("greenhouse_applied.txt"))
    assert len(fake.calls) == 2
    assert ext.status_signal == "applied"


def test_double_failure_is_flagged_not_guessed():
    clf, fake = make_classifier(["nope", "still nope"])
    ext = clf.classify(load_fixture("greenhouse_applied.txt"))
    assert ext.relevance == "unknown"
    assert ext.confidence == 0.0
