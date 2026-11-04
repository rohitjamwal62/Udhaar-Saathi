import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "database"), str(ROOT / "backend")]

# Tests run against their OWN database so real data is never touched.
os.environ["PGDATABASE"] = "udhaar_saathi_test"
# A hosted DATABASE_URL (e.g. Neon) in .env must NEVER be used by tests: they truncate tables.
os.environ["DATABASE_URL"] = ""
os.environ["USE_LOCAL_DB"] = "1"  # tests use a local scratch DB, never the live Neon database
os.environ.update({
    "DJANGO_SETTINGS_MODULE": "config.settings", "DJANGO_DEBUG": "true", "OTP_SENDER": "memory",
    "PAYMENT_GATEWAY": "fake", "THROTTLE_AUTH": "100000/min", "THROTTLE_SYNC": "100000/min",
    "THROTTLE_WEBHOOK": "100000/min", "DJANGO_ALLOWED_HOSTS": "testserver,localhost", "OTP_RESEND_COOLDOWN_SECONDS": "0",
    # the website: never send real email or call Google from tests
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend", "EMAIL_HOST_USER": "", "EMAIL_HOST_PASSWORD": "",
    "GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": "", "GOOGLE_REFRESH_TOKEN": "", "GOOGLE_DRIVE_FOLDER_ID": "",
    "EMAIL_OTP_RESEND_SECONDS": "0", "SUPPORT_EMAIL": "support@example.test",
})

import django  # noqa: E402

django.setup()

import pytest  # noqa: E402
from django.core import mail  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402

import create_tables  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    cfg = create_tables.load_env()
    assert cfg["dbname"].endswith("_test"), "refusing to run tests on a non-test database"
    create_tables.create(cfg)                  # the app tables (database/create_tables.py)
    call_command("migrate", verbosity=0)       # Django's own tables + the website tables


@pytest.fixture(autouse=True)
def _clean():
    from apps.accounts import otp
    assert connection.settings_dict["NAME"].endswith("_test")
    with connection.cursor() as cur:
        cur.execute("TRUNCATE users, otp_challenges, gateway_webhook_events, auth_user, web_emailotp, "
                    "web_contactmessage, django_session, django_admin_log CASCADE")
    cache.clear()
    otp.MEMORY_OUTBOX.clear()
    mail.outbox.clear() if hasattr(mail, "outbox") else None
    yield
