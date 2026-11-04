"""One-time Google connection (Drive + Gmail API).

    python manage.py google_consent --redirect https://www.google.com/                 # prints the page to open
    python manage.py google_consent --redirect https://www.google.com/ --code 4/0A...  # saves the refresh token
"""
import pathlib
import re
import urllib.parse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.web import google

SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/gmail.send"]


class Command(BaseCommand):
    help = "Print the Google consent URL, or exchange the returned code for a refresh token and store it in backend/.env."

    def add_arguments(self, parser):
        parser.add_argument("--redirect", required=True)
        parser.add_argument("--code")
        parser.add_argument("--env-file", default=str(settings.BASE_DIR / ".env"))

    def handle(self, *args, **opts):
        if not opts["code"]:
            q = urllib.parse.urlencode({"client_id": settings.GOOGLE_CLIENT_ID, "redirect_uri": opts["redirect"], "response_type": "code",
                                        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent"}, quote_via=urllib.parse.quote)
            self.stdout.write("Open this address, approve access, then copy the code= value from the page you land on:\n\n"
                              "https://accounts.google.com/o/oauth2/v2/auth?" + q)
            return
        code = urllib.parse.unquote(opts["code"].split("code=")[-1].split("&")[0])
        tokens = google.exchange_code(code, opts["redirect"])
        refresh = tokens.get("refresh_token")
        if not refresh:
            raise CommandError("Google returned no refresh token. Repeat the consent with prompt=consent and a fresh code.")
        p = pathlib.Path(opts["env_file"])
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        text = re.sub(r"^GOOGLE_REFRESH_TOKEN=.*$", "", text, flags=re.M).rstrip("\n") + f"\nGOOGLE_REFRESH_TOKEN={refresh}\n"
        p.write_text(text, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Refresh token saved to {p} (scopes: {tokens.get('scope')})."))
