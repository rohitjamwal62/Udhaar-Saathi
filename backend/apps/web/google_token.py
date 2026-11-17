"""Remembers the Google refresh token between refreshes.

The structure:
  1. every time an access token is fetched, the refresh token used is READ from this store (falling back to the
     GOOGLE_REFRESH_TOKEN setting the first time),
  2. after a successful refresh the refresh token is SAVED back, replacing the previous copy. If Google sent a new refresh
     token in its answer, THAT one is saved and used from then on.

What Google actually does (checked 17 November 2026): refreshing returns only a new access token (`access_token`, `expires_in`,
`scope`, `token_type`), never a new refresh token, so in practice the saved token stays the same. What keeps it alive is the
consent screen being "In production" and the token being used regularly. This store simply makes sure nothing is lost if Google
ever does rotate it, and that a re-consent (a changed GOOGLE_REFRESH_TOKEN setting) always wins over an older saved copy.

Where it is kept:
  * the database (default): Render erases local files on every deploy, so a file there would be lost,
  * a JSON file, when GOOGLE_TOKEN_FILE is set (for a machine with a permanent disk). Written atomically, owner-only permissions.

Nothing here ever logs or returns the token itself; a failure to read or write the store never stops email or Drive from
working (the setting is used instead).
"""
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

log = logging.getLogger("google.token")


def fingerprint(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


# ───────────────────────── stores ─────────────────────────
class _FileStore:
    name = "file"

    def __init__(self, path: str):
        self.path = Path(path)

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None

    def save(self, refresh_token: str, seed_hash: str, rotations: int) -> None:
        payload = {"refresh_token": refresh_token, "seed_hash": seed_hash, "rotations": rotations,
                   "updated_at": datetime.now(timezone.utc).isoformat()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".google_token-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            try:
                os.chmod(tmp, 0o600)                      # owner only (a no-op on Windows)
            except OSError:
                pass
            os.replace(tmp, self.path)                    # atomic: a crash never leaves a half-written file
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


class _DbStore:
    name = "database"

    def load(self) -> dict | None:
        from .models import GoogleToken
        row = GoogleToken.objects.order_by("id").first()
        if not row:
            return None
        return {"refresh_token": row.refresh_token, "seed_hash": row.seed_hash, "rotations": row.rotations,
                "updated_at": row.updated_at.isoformat()}

    def save(self, refresh_token: str, seed_hash: str, rotations: int) -> None:
        from .models import GoogleToken
        row = GoogleToken.objects.order_by("id").first()
        if row is None:
            GoogleToken.objects.create(refresh_token=refresh_token, seed_hash=seed_hash, rotations=rotations)
        elif (row.refresh_token, row.seed_hash, row.rotations) != (refresh_token, seed_hash, rotations):
            row.refresh_token, row.seed_hash, row.rotations = refresh_token, seed_hash, rotations
            row.save()
        else:
            row.save(update_fields=["updated_at"])        # same token: just note that it was used


def store():
    path = (getattr(settings, "GOOGLE_TOKEN_FILE", "") or "").strip()
    return _FileStore(path) if path else _DbStore()


# ───────────────────────── the two operations ─────────────────────────
def _saved_for_current_setting() -> dict | None:
    """The saved token, but only if it started from the CURRENT GOOGLE_REFRESH_TOKEN setting. After a re-consent the setting
    changes, and an older saved copy must never override the fresh token."""
    try:
        saved = store().load()
    except Exception:  # noqa: BLE001  (a database or file problem must never stop email)
        log.warning("could not read the saved Google token; using the setting", exc_info=True)
        return None
    if saved and saved.get("refresh_token") and saved.get("seed_hash") == fingerprint(settings.GOOGLE_REFRESH_TOKEN):
        return saved
    return None


def current() -> str:
    """The refresh token to use right now."""
    saved = _saved_for_current_setting()
    return saved["refresh_token"] if saved else settings.GOOGLE_REFRESH_TOKEN


def record(used: str, new: str | None = None) -> bool:
    """Call after a successful refresh. Saves the token (the NEW one if Google sent one, otherwise the one just used),
    replacing the previous copy. Returns True when Google really replaced the token."""
    saved = _saved_for_current_setting()
    rotations = (saved or {}).get("rotations", 0)
    replaced = bool(new) and new != used
    keep = new if replaced else used
    try:
        store().save(keep, fingerprint(settings.GOOGLE_REFRESH_TOKEN), rotations + (1 if replaced else 0))
    except Exception:  # noqa: BLE001
        log.warning("could not save the Google token (it keeps working from the setting)", exc_info=True)
        return replaced
    if replaced:
        log.info("Google issued a replacement refresh token; it was saved and will be used from now on")
    return replaced


def describe() -> dict:
    """Facts for the admin diagnostics page. Never includes the token."""
    s = store()
    try:
        saved = s.load()
    except Exception:  # noqa: BLE001
        saved = None
    return {"stored_in": s.name, "saved_token_exists": bool(saved and saved.get("refresh_token")),
            "replaced_by_google_times": (saved or {}).get("rotations", 0), "last_saved_at": (saved or {}).get("updated_at")}
