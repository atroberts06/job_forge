#!/usr/bin/env python3
"""Sync resume-tailor build artifacts to Google Drive (ADR-006 CD deploy step).

Authenticates with a user OAuth refresh token so uploads can target a
personal Google Drive folder (DEF-001). Service-account auth is not used.

Uploads tailored-resume.md, tailored-outreach.md, the sandbox application
.docx files (resume and cover letter), and engineering-log.md per resume-tailor
sandbox. job-description.md and tailored-cover-letter.md remain in git.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/{id}"
SYNC_RESULT_PATH = Path("dist/drive-sync-result.json")
DRIVE_RESUME_NAME = "tailored-resume.md"
DRIVE_ENGINEERING_LOG_NAME = "engineering-log.md"
DRIVE_OUTREACH_NAME = "tailored-outreach.md"


def get_drive_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    client_id = os.environ.get("GDRIVE_CLIENT_ID")
    client_secret = os.environ.get("GDRIVE_CLIENT_SECRET")
    refresh_token = os.environ.get("GDRIVE_REFRESH_TOKEN")

    missing = [
        name
        for name, value in (
            ("GDRIVE_CLIENT_ID", client_id),
            ("GDRIVE_CLIENT_SECRET", client_secret),
            ("GDRIVE_REFRESH_TOKEN", refresh_token),
        )
        if not value
    ]
    if missing:
        print(
            "ERROR: Missing required OAuth secrets: " + ", ".join(missing),
            file=sys.stderr,
        )
        sys.exit(1)

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    credentials.refresh(Request())
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_folder(service, name: str, parent_id: str) -> str | None:
    safe_name = _escape_query(name)
    query = (
        f"name = '{safe_name}' and "
        f"'{parent_id}' in parents and "
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    result = service.files().list(q=query, fields="files(id, name)", pageSize=1).execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]
    return None


def find_or_create_folder(service, name: str, parent_id: str) -> str:
    existing = find_folder(service, name, parent_id)
    if existing:
        return existing

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def folder_url(folder_id: str) -> str:
    return DRIVE_FOLDER_URL.format(id=folder_id)


def write_sync_result(folders: list[dict]) -> None:
    SYNC_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"folders": folders}
    SYNC_RESULT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def upload_file(
    service, local_path: Path, parent_id: str, drive_name: str | None = None
) -> str:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    name = drive_name or local_path.name
    safe_name = _escape_query(name)
    query = f"name = '{safe_name}' and '{parent_id}' in parents and trashed = false"
    existing = service.files().list(q=query, fields="files(id)", pageSize=1).execute()
    media = MediaFileUpload(str(local_path), resumable=True)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if existing.get("files"):
                file_id = existing["files"][0]["id"]
                updated = (
                    service.files()
                    .update(fileId=file_id, media_body=media)
                    .execute()
                )
                return updated["id"]

            metadata = {"name": name, "parents": [parent_id]}
            created = (
                service.files()
                .create(body=metadata, media_body=media, fields="id")
                .execute()
            )
            return created["id"]
        except HttpError as exc:
            if attempt == MAX_RETRIES:
                raise
            print(f"  retry {attempt}/{MAX_RETRIES} after error: {exc}")
            time.sleep(RETRY_DELAY_SECONDS * attempt)


def artifact_uploads(entry: dict) -> tuple[tuple[str | None, str | None], ...]:
    return (
        (entry.get("resume_artifact"), DRIVE_RESUME_NAME),
        (entry.get("engineering_log_artifact"), DRIVE_ENGINEERING_LOG_NAME),
        (entry.get("outreach_artifact"), DRIVE_OUTREACH_NAME),
        (entry.get("resume_docx_artifact"), entry.get("resume_docx_name")),
        (entry.get("cover_letter_docx_artifact"), entry.get("cover_letter_docx_name")),
    )


def main() -> int:
    root_folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not root_folder_id:
        print("ERROR: GDRIVE_FOLDER_ID secret is not set.", file=sys.stderr)
        return 1

    manifest_path = Path("dist/resume-tailor-manifest.json")
    if not manifest_path.is_file():
        print("No manifest found — nothing to deploy.")
        write_sync_result([])
        return 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("resume_tailor", [])
    if not entries:
        print("Manifest contains no resume-tailor entries — skipping deploy.")
        write_sync_result([])
        return 0

    service = get_drive_service()
    folders: list[dict] = []

    for entry in entries:
        company = entry["company_name"]
        role = entry["role_title"]
        artifacts = artifact_uploads(entry)

        company_folder_id = find_or_create_folder(service, company, root_folder_id)
        role_folder_id = find_or_create_folder(service, role, company_folder_id)

        for artifact, drive_name in artifacts:
            if not artifact or not drive_name:
                print(
                    f"  WARNING: missing manifest field for {drive_name}, "
                    f"skipping {company}/{role}"
                )
                continue
            local_path = Path(artifact)
            if not local_path.is_file():
                print(
                    f"  WARNING: missing {local_path}, skipping "
                    f"{drive_name} for {company}/{role}"
                )
                continue
            file_id = upload_file(
                service, local_path, role_folder_id, drive_name=drive_name
            )
            print(f"  uploaded {drive_name} -> {company}/{role} (file {file_id})")

        folders.append(
            {
                "resume_tailor_directory": entry.get("resume_tailor_directory") or "",
                "artifacts_url": folder_url(role_folder_id),
            }
        )

    write_sync_result(folders)
    print("Google Drive sync completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
