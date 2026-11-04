"""Google OAuth (refresh-token flow), Google Drive and the Gmail API, over plain HTTPS with `requests`.

Why HTTPS: Render's free web services cannot use SMTP ports, and a drive/gmail client library is not needed.
The refresh token comes from a one-time consent (see `manage.py google_consent`).
"""
import json
import logging
import time
import uuid

import requests
from django.conf import settings

log = logging.getLogger("google")
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
GMAIL_SEND = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

_token = {"value": "", "exp": 0.0}


class GoogleError(Exception):
    pass


def configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.GOOGLE_REFRESH_TOKEN)


def drive_configured() -> bool:
    return configured() and bool(settings.GOOGLE_DRIVE_FOLDER_ID)


def access_token() -> str:
    """A valid access token, refreshed from the refresh token when it is about to expire."""
    if _token["value"] and time.time() < _token["exp"] - 60:
        return _token["value"]
    if not configured():
        raise GoogleError("Google is not connected yet (missing refresh token).")
    r = requests.post(TOKEN_URL, data={
        "client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "refresh_token": settings.GOOGLE_REFRESH_TOKEN, "grant_type": "refresh_token"}, timeout=20)
    if r.status_code != 200:
        err = r.json().get("error", "") if r.headers.get("content-type", "").startswith("application/json") else ""
        hint = " The refresh token has expired or was revoked: connect Google again." if err == "invalid_grant" else ""
        raise GoogleError(f"Google refused the token request ({r.status_code} {err}).{hint}")
    data = r.json()
    _token.update(value=data["access_token"], exp=time.time() + int(data.get("expires_in", 3600)))
    return _token["value"]


def _auth() -> dict:
    return {"Authorization": f"Bearer {access_token()}"}


def drive_upload(name: str, data: bytes, mime: str = "application/octet-stream", folder_id: str | None = None) -> dict:
    """Upload bytes into the configured Drive folder. Returns {'id', 'name', 'webViewLink', 'size'}."""
    folder_id = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID
    if not folder_id:
        raise GoogleError("GOOGLE_DRIVE_FOLDER_ID is not set.")
    boundary = "udhaar-" + uuid.uuid4().hex
    meta = json.dumps({"name": name, "parents": [folder_id]}).encode()
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + meta +
            f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode() + data + f"\r\n--{boundary}--".encode())
    r = requests.post(UPLOAD, params={"uploadType": "multipart", "supportsAllDrives": "true",
                                      "fields": "id,name,webViewLink,size,mimeType"},
                      headers={**_auth(), "Content-Type": f"multipart/related; boundary={boundary}"}, data=body, timeout=120)
    if r.status_code not in (200, 201):
        raise GoogleError(f"Drive upload failed ({r.status_code}): {r.text[:200]}")
    return r.json()


def drive_download(file_id: str) -> tuple[bytes, str]:
    r = requests.get(f"{DRIVE}/files/{file_id}", params={"alt": "media", "supportsAllDrives": "true"}, headers=_auth(), timeout=120)
    if r.status_code != 200:
        raise GoogleError(f"Drive download failed ({r.status_code}).")
    return r.content, r.headers.get("content-type", "application/octet-stream")


def drive_list(folder_id: str | None = None, limit: int = 100) -> list[dict]:
    folder_id = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID
    r = requests.get(f"{DRIVE}/files", params={"q": f"'{folder_id}' in parents and trashed = false", "pageSize": limit,
                                               "fields": "files(id,name,size,mimeType,webViewLink,createdTime)",
                                               "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"},
                     headers=_auth(), timeout=30)
    if r.status_code != 200:
        raise GoogleError(f"Drive list failed ({r.status_code}): {r.text[:200]}")
    return r.json().get("files", [])


def drive_delete(file_id: str) -> None:
    r = requests.delete(f"{DRIVE}/files/{file_id}", params={"supportsAllDrives": "true"}, headers=_auth(), timeout=30)
    if r.status_code not in (200, 204):
        raise GoogleError(f"Drive delete failed ({r.status_code}).")


def gmail_send_raw(raw_b64url: str) -> dict:
    r = requests.post(GMAIL_SEND, headers={**_auth(), "Content-Type": "application/json"}, json={"raw": raw_b64url}, timeout=30)
    if r.status_code != 200:
        raise GoogleError(f"Gmail API send failed ({r.status_code}): {r.text[:200]}")
    return r.json()


def exchange_code(code: str, redirect_uri: str) -> dict:
    """One-time: swap the consent `code` for tokens (used by `manage.py google_consent --code ...`)."""
    r = requests.post(TOKEN_URL, data={"client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET,
                                       "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri}, timeout=20)
    if r.status_code != 200:
        raise GoogleError(f"Code exchange failed ({r.status_code}): {r.text[:300]}")
    return r.json()
