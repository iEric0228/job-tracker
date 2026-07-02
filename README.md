# Job application tracker

Parses your Gmail inbox (read-only), classifies job-related emails with a local LLM, and visualizes your pipeline — no manual data entry. Single-user, local-first, SQLite. Email bodies never leave your machine: classification runs on Ollama.

Pipeline per sync: Gmail date-window fetch → cheap prefilter (ATS sender domains + keywords, job-alert digests excluded) → Ollama structured extraction → grouping into applications (thread continuity + fuzzy company/role matching) → events stored in SQLite → statuses derived, never guessed.

## Definitions the charts use

- **Funnel** counts *furthest stage ever reached*. An application that went applied → assessment → rejected still counts in the assessment bar. `current_status` and `furthest_stage` are tracked separately.
- **Ghosted** is derived at read time, never stored: no employer email for `ghost_days` (default 21) and not in a terminal state. If they finally reply, the next load flips it back to active. Two buckets: *ghosted-after-applying* (never got past the auto-confirmation) vs *ghosted-in-process* (real touchpoint, then silence).
- **Response** = any human-written or scheduling email, or any stage at recruiter screen or beyond.
- Explicit rejections and ghosting are always reported separately.

## Setup

Prerequisites: [uv](https://docs.astral.sh/uv/) and [Ollama](https://ollama.com) ≥ 0.5 (structured outputs).

```bash
cd job-tracker
uv sync
ollama pull qwen2.5:7b   # default model; change in config.toml
```

### Google Cloud OAuth (one-time)

1. Go to [console.cloud.google.com](https://console.cloud.google.com), create a project (e.g. `job-tracker`).
2. APIs & Services → Library → enable **Gmail API**.
3. APIs & Services → OAuth consent screen → External → fill in app name + your email → add **yourself as a Test user**.
4. APIs & Services → Credentials → Create credentials → **OAuth client ID** → Application type **Desktop app** → download the JSON → save it as `credentials.json` in the repo root.

Caveat: while the consent screen stays in "Testing" mode, Google expires the refresh token after ~7 days. When sync starts failing with an auth error, delete `token.json` and run the sync again to re-authorize in the browser. Annoying but normal for personal-use OAuth apps with a restricted scope.

### First run

```bash
uv run jobtracker-sync                      # opens browser for read-only Gmail consent
uv run streamlit run dashboard/app.py      # dashboard at localhost:8501
```

The first sync backfills `backfill_days` (default 180). Every candidate email is classified by the local model, so the backfill takes a few seconds per job email on typical hardware; later runs are incremental and near-instant. `--since 2026-01-01` forces a rescan from a date (already-processed messages are skipped, not re-classified).

## Configuration (`config.toml`)

`backfill_days` / `overlap_days` — sync window; `ghost_days` — silence threshold; `confidence_threshold` — extractions below it are flagged in the dashboard's "Needs review" table; `[ollama]` — host and model; `[categories]` — job-track buckets offered to the LLM; `[company_aliases]` — e.g. AWS → Amazon; `[prefilter]` — ATS domains, keywords, and noise lists.

## Design decisions

- **Date-window sync + message-id dedup, not `historyId`.** Gmail history expires after ~a week of inactivity and needs a fallback path anyway; the UNIQUE message-id constraint already makes re-runs no-ops, so one code path covers backfill, incremental, and forced rescans.
- **Grouping doesn't trust threads.** ATSes routinely send rejections in a fresh thread, so application identity is normalized (company, fuzzy role) with thread continuity as a shortcut. Req codes (`70140 …`, `R440149 …`) are stripped before matching. Ambiguous attachments (a rejection naming no role) are guessed *and flagged*, never silent.
- **The Date header is authoritative** — the LLM is never asked for dates.
- **`email_kind` distinguishes human vs automated email** — response rate and the two ghost buckets depend on it; stage alone can't tell a template rejection from a recruiter's note.
- **One LLM provider wired.** `classifier.py` defines a two-method protocol; to add Anthropic/OpenAI later, implement `classify(EmailMessage) -> Extraction` and swap the constructor in `cli.py`. Nothing else changes.

## Tests

```bash
uv run pytest      # 34 tests: prefilter, grouping, state/ghost logic, classifier parsing, sync idempotency
uv run ruff check .
```

Fixtures in `tests/fixtures/` include real (redacted) Workday and Staples emails plus synthetic Greenhouse/Lever/Ashby ones and noise cases. The classifier is faked in tests — no Ollama needed to run them.

## Not in v1 (deliberately)

Follow-up reminders, manual correction UI, needs-action view, filters/search, CSV export, time-in-stage analytics, dedup review UI. The schema supports them; the code doesn't pretend to.
