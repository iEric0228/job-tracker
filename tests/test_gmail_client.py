from __future__ import annotations

from jobtracker.gmail_client import build_search_terms


def test_search_terms_or_group_covers_all_inclusion_rules(cfg):
    terms = build_search_terms(cfg)
    # One OR-group ({} is Gmail's any-of syntax) holding every inclusion rule.
    assert terms.startswith("{") and terms.endswith("}")
    assert "from:greenhouse.io" in terms
    assert "from:myworkday.com" in terms
    assert "from:jobs-noreply@linkedin.com" in terms  # allow_senders beat noise rules
    assert 'subject:"interview"' in terms
    assert 'subject:"talent acquisition"' in terms  # multi-word keywords stay quoted
    assert '"thank you for applying"' in terms
    assert '"moving forward with other candidates"' in terms


def test_search_terms_contains_no_exclusion_rules(cfg):
    # Noise filtering stays local: it needs the skipped-table audit trail,
    # and Gmail's negative operators would silently hide mail from it.
    terms = build_search_terms(cfg)
    assert "linkedin.com " not in terms.replace("jobs-noreply@linkedin.com", "")
    assert "-from:" not in terms
