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

from . import google_token

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


def _refresh_call(refresh_token: str) -> requests.Response:
    return requests.post(TOKEN_URL, data={
        "client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token, "grant_type": "refresh_token"}, timeout=20)


def _error_of(r: requests.Response) -> str:
    return r.json().get("error", "") if r.headers.get("content-type", "").startswith("application/json") else ""


def access_token() -> str:
    """A valid access token, refreshed from the refresh token when it is about to expire.

    The refresh token is read from the store (apps/web/google_token.py), and saved back after every successful refresh,
    replacing the previous copy; if Google ever sends a new refresh token it is saved and used from then on.
    """
    if _token["value"] and time.time() < _token["exp"] - 60:
        return _token["value"]
    if not configured():
        raise GoogleError("Google is not connected yet (missing refresh token).")
    used = google_token.current()
    r = _refresh_call(used)
    if r.status_code != 200 and used != settings.GOOGLE_REFRESH_TOKEN and _error_of(r) == "invalid_grant":
        # the saved copy failed: fall back once to the token in the settings (and heal the store if that one works)
        log.warning("the saved Google token was refused; trying the one in the settings")
        used = settings.GOOGLE_REFRESH_TOKEN
        r = _refresh_call(used)
    if r.status_code != 200:
        err = _error_of(r)
        hint = " The refresh token has expired or was revoked: connect Google again." if err == "invalid_grant" else ""
        raise GoogleError(f"Google refused the token request ({r.status_code} {err}).{hint}")
    data = r.json()
    google_token.record(used, data.get("refresh_token"))
    _token.update(value=data["access_token"], exp=time.time() + int(data.get("expires_in", 3600)))
    return _token["value"]


def token_status() -> str:
    """'ok', 'not_configured', 'token_expired' (re-consent needed) or 'unreachable'. Cached so health checks stay cheap."""
    from django.core.cache import cache
    cached = cache.get("google:token_status")
    if cached:
        return cached
    if not configured():
        state = "not_configured"
    else:
        try:
            access_token()
            state = "ok"
        except GoogleError as e:
            state = "token_expired" if "invalid_grant" in str(e) else "unreachable"
        except requests.RequestException:
            state = "unreachable"
    cache.set("google:token_status", state, 300 if state == "ok" else 60)
    return state


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
