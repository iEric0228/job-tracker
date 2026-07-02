"""Gmail access, read-only scope.

Incremental sync is a date-window query plus message-id dedup — deliberately
not historyId: history expires after roughly a week of inactivity and would
need a fallback path anyway, while the UNIQUE message_id constraint already
makes re-processing a no-op.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from jobtracker.models import EmailMessage

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailClient:
    def __init__(self, credentials_path: Path, token_path: Path):
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._service = None

    def _service_handle(self):
        if self._service is None:
            creds = None
            if self._token_path.exists():
                creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self._credentials_path), SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                self._token_path.write_text(creds.to_json(), encoding="utf-8")
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def list_message_ids(self, after_epoch: int) -> list[str]:
        service = self._service_handle()
        ids: list[str] = []
        token = None
        while True:
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=f"after:{after_epoch}", maxResults=500, pageToken=token)
                .execute()
            )
            ids.extend(m["id"] for m in resp.get("messages", []))
            token = resp.get("nextPageToken")
            if not token:
                return ids

    def get_metadata(self, message_id: str) -> EmailMessage:
        resp = (
            self._service_handle()
            .users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject"],
            )
            .execute()
        )
        return _from_response(resp, body="")

    def get_full(self, message_id: str) -> EmailMessage:
        resp = (
            self._service_handle()
            .users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return _from_response(resp, body=_extract_body(resp.get("payload", {})))


def _from_response(resp: dict, body: str) -> EmailMessage:
    headers = {h["name"].lower(): h["value"] for h in resp.get("payload", {}).get("headers", [])}
    date = datetime.fromtimestamp(int(resp["internalDate"]) / 1000, tz=timezone.utc)
    return EmailMessage(
        message_id=resp["id"],
        thread_id=resp.get("threadId", ""),
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        date=date,
        body=body,
        snippet=resp.get("snippet", ""),
    )


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def _walk_parts(payload: dict) -> Iterator[dict]:
    yield payload
    for part in payload.get("parts", []) or []:
        yield from _walk_parts(part)


def _extract_body(payload: dict) -> str:
    plain: list[str] = []
    html: list[str] = []
    for part in _walk_parts(payload):
        data = part.get("body", {}).get("data")
        if not data:
            continue
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            plain.append(_decode(data))
        elif mime == "text/html":
            html.append(_decode(data))
    if plain:
        return "\n".join(plain).strip()
    if html:
        return BeautifulSoup("\n".join(html), "html.parser").get_text(" ", strip=True)
    return ""
