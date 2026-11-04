"""Upload files to the Google Drive folder, skipping names already there.

    python manage.py upload_docs_to_drive FILE [FILE ...]
    python manage.py upload_docs_to_drive --list x
"""
import mimetypes
import pathlib

from django.core.management.base import BaseCommand, CommandError

from apps.web import google

# Files that look like secrets are never uploaded, whatever the command line says.
NEVER = ("secret", "token", ".env", "password", "credential", "keystore", ".pem", ".key", "backup-codes", "local.txt")


class Command(BaseCommand):
    help = "Upload documents to the configured Drive folder."

    def add_arguments(self, parser):
        parser.add_argument("files", nargs="+")
        parser.add_argument("--list", action="store_true", help="only list what is in the folder")

    def handle(self, *args, **opts):
        if not google.drive_configured():
            raise CommandError("Google Drive is not connected: GOOGLE_REFRESH_TOKEN is missing (run google_consent).")
        existing = {f["name"]: f for f in google.drive_list()}
        if opts["list"]:
            for name, f in sorted(existing.items()):
                self.stdout.write(f"{name}  ({f.get('size', '?')} bytes)  {f.get('webViewLink', '')}")
            return
        for path in opts["files"]:
            p = pathlib.Path(path)
            if not p.is_file():
                self.stderr.write(f"missing: {p}")
                continue
            if any(bad in p.name.lower() for bad in NEVER):
                self.stderr.write(f"refused (looks like a secret file): {p.name}")
                continue
            if p.name in existing:
                self.stdout.write(f"already in Drive: {p.name}")
                continue
            info = google.drive_upload(p.name, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")
            self.stdout.write(self.style.SUCCESS(f"uploaded: {p.name} -> {info.get('webViewLink', info['id'])}"))
