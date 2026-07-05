"""Entry point for `jobtracker-sync`."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from jobtracker import db
from jobtracker.classifier import OllamaClassifier
from jobtracker.config import load_config
from jobtracker.gmail_client import GmailClient, build_search_terms
from jobtracker.sync import run_sync


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync job-application emails from Gmail.")
    parser.add_argument("--config", default="config.toml", help="path to config.toml")
    parser.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="ignore saved sync state and scan from this date instead",
    )
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="list every message in the window instead of the targeted Gmail "
        "search; use to audit what the search terms would miss",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    override = None
    if args.since:
        override = int(
            datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        )

    conn = db.connect(cfg.db_path)
    search_terms = "" if args.full_scan else build_search_terms(cfg)
    mail = GmailClient(cfg.credentials_path, cfg.token_path, search_terms=search_terms)
    classifier = OllamaClassifier(cfg.ollama_host, cfg.ollama_model, cfg.categories)
    result = run_sync(conn, cfg, mail, classifier, override_start_epoch=override)
    print(result.summary())


if __name__ == "__main__":
    main()
