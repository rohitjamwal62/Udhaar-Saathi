"""
LenDen Saathi backend settings.

The PostgreSQL schema is owned by ../database/create_tables.py (one file, run it first).
Django is used as the web/API framework only: there are no Django models or migrations.
Secrets come from the environment / backend/.env (never committed).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v:  # blank values must not shadow a real value from another file
                os.environ.setdefault(k.strip(), v)


# backend/.env first, then the database folder's .env (shares the PG* variables)
_load_env(BASE_DIR / ".env")
_load_env(BASE_DIR.parent / "database" / ".env")

env = os.environ.get


def _bool(name: str, default: str = "false") -> bool:
    return env(name, default).strip().lower() in ("1", "true", "yes")


APP_ENV = env("APP_ENV", "local")  # local | development | staging | production
DEBUG = _bool("DJANGO_DEBUG")
SECRET_KEY = env("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-" + "x" * 40
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DEBUG is false")

ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,10.0.2.2").split(",") if h.strip()]
# Render tells the service its public hostname (e.g. udhaarsaathi-api.onrender.com).
if env("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(env("RENDER_EXTERNAL_HOSTNAME"))

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "apps.common",
    "apps.accounts",
    "apps.shops",
    "apps.sync",
    "apps.subscriptions",
    "apps.system",
    "apps.legacy",   # unmanaged models over the tables created by database/create_tables.py (for Django admin)
    "apps.web",      # the public website, email-OTP sign-up/login, documents on Google Drive
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "apps.web.middleware.IgnoreAcceptLanguageMiddleware",   # English unless the visitor picks Hindi (cookie)
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.common.middleware.RequestIdMiddleware",
    "apps.web.middleware.AdminLoginThrottleMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.template.context_processors.i18n",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "apps.web.context_processors.site",
    ]},
}]

def _database_from_env() -> dict:
    """The live database is Neon (hosted PostgreSQL), given as DATABASE_URL.
    There is deliberately NO silent fallback to a local database: without DATABASE_URL the server refuses to
    start. Only the test suite (and an explicit USE_LOCAL_DB=1) may use a local PostgreSQL."""
    url = env("DATABASE_URL", "").strip()
    if not url:
        if env("USE_LOCAL_DB", "") == "1":
            return {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": env("PGDATABASE", "udhaar_saathi"),
                "USER": env("PGUSER", "postgres"),
                "PASSWORD": env("PGPASSWORD", ""),
                "HOST": env("PGHOST", "localhost"),
                "PORT": env("PGPORT", "5432"),
                "CONN_MAX_AGE": 60,
            }
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(
            "DATABASE_URL is not set. Put your Neon connection string in backend/.env "
            "(DATABASE_URL=postgresql://...). This server does not use a local database.")
    from urllib.parse import parse_qsl, unquote, urlparse

    u = urlparse(url)
    options = {k: v for k, v in parse_qsl(u.query) if k in ("sslmode", "channel_binding", "sslrootcert")}
    options.setdefault("sslmode", "require")  # hosted databases must use TLS
    pooled = "-pooler" in (u.hostname or "")   # Neon's PgBouncer endpoint (transaction pooling)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": (u.path or "/").lstrip("/") or "postgres",
        "USER": unquote(u.username or ""),
        "PASSWORD": unquote(u.password or ""),
        "HOST": u.hostname,
        "PORT": str(u.port or 5432),
        # Neon pauses idle databases and drops their connections, so re-check a reused connection before using
        # it (CONN_HEALTH_CHECKS) and keep TCP alive. A pooler hands out short-lived connections: don't reuse.
        "CONN_MAX_AGE": 0 if pooled else 60,
        "CONN_HEALTH_CHECKS": not pooled,
        "DISABLE_SERVER_SIDE_CURSORS": pooled,
        "OPTIONS": {**options, "connect_timeout": 20, "keepalives": 1, "keepalives_idle": 30,
                    "keepalives_interval": 10, "keepalives_count": 5},
    }


DATABASES = {"default": _database_from_env()}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en"
USE_I18N = True
LANGUAGES = [("en", "English"), ("hi", "हिन्दी")]
LOCALE_PATHS = [BASE_DIR / "locale"]
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365      # the visitor's choice is remembered for a year
LANGUAGE_COOKIE_SAMESITE = "Lax"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}  # use Redis in production

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.common.auth.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "apps.common.errors.exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        "auth": env("THROTTLE_AUTH", "30/min"),
        "webhook": env("THROTTLE_WEBHOOK", "300/min"),
        "sync": env("THROTTLE_SYNC", "120/min"),
    },
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "LenDen Saathi API",
    "DESCRIPTION": "Backend for the LenDen Saathi Android app. Money is integer paise.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ── Auth ──
JWT_ACCESS_MINUTES = int(env("JWT_ACCESS_MINUTES", "15"))
REFRESH_TOKEN_DAYS = int(env("REFRESH_TOKEN_DAYS", "30"))
OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = int(env("OTP_RESEND_COOLDOWN_SECONDS", "30"))
OTP_MAX_PER_HOUR = 6
LOGIN_MAX_FAILURES = int(env("LOGIN_MAX_FAILURES", "10"))        # per mobile, per 15 minutes
# 'console' prints the OTP to this server's stdout (development only, needs DEBUG).
# Production must plug in a real SMS provider (DLT registered); see apps/accounts/otp.py.
# Which ledger the WEBSITE reads and writes (see docs/UNIFY_LEDGER_PLAN.md):
#   legacy  = the website's own tables (web_party / web_ledgerentry): today's behaviour.
#   unified = the app's ledger (shops / customers / ledger_events), so app and website share one truth.
# The switch exists so the migration can be rehearsed and rolled back. 'unified' is not implemented yet.
LEDGER_BACKEND = env("LEDGER_BACKEND", "legacy")
if LEDGER_BACKEND not in ("legacy", "unified"):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("LEDGER_BACKEND must be 'legacy' or 'unified'")

OTP_SENDER = env("OTP_SENDER", "console")
# TEST DEPLOYMENTS ONLY: lets the 'console' sender print OTPs into the server log when DEBUG is off (for example
# on Render before an SMS provider exists). Anyone who can read the log can read the OTPs. Turn it OFF for real users.
ALLOW_DEV_OTP_IN_LOGS = _bool("ALLOW_DEV_OTP_IN_LOGS")

# ── Payments (Razorpay Pay-as-you-go). 'fake' is for local testing only (needs DEBUG). ──
PAYMENT_GATEWAY = env("PAYMENT_GATEWAY", "fake" if DEBUG else "razorpay")
RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", "")
GATEWAY_FEE_BPS = int(env("GATEWAY_FEE_BPS", "0"))                  # internal cost reporting only
TAXES_NOTE = env("TAXES_NOTE", "Taxes: to be confirmed. Any applicable tax is shown before you pay.")

# ── App update control (also stored in app_config table, which wins when present) ──
APP_LATEST_VERSION = env("APP_LATEST_VERSION", "1.0.0")
APP_MIN_VERSION = env("APP_MIN_VERSION", "1.0.0")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_REDIRECT_EXEMPT = [r"^health/"]  # the platform health check may arrive without HTTPS headers
if not DEBUG:
    SECURE_SSL_REDIRECT = _bool("SECURE_SSL_REDIRECT", "true")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}


# ───────────── Website: static files, sessions, auth ─────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
AUTHENTICATION_BACKENDS = ["apps.web.auth_backends.EmailOrUsernameBackend", "django.contrib.auth.backends.ModelBackend"]
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
SESSION_COOKIE_HTTPONLY = True
SITE_NAME = "LenDen Saathi"
SITE_URL = env("SITE_URL") or env("RENDER_EXTERNAL_URL") or "http://localhost:8000"
SUPPORT_EMAIL = env("SUPPORT_EMAIL", "rohitjamwal62@gmail.com")
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
if env("RENDER_EXTERNAL_URL"):
    CSRF_TRUSTED_ORIGINS.append(env("RENDER_EXTERNAL_URL"))
ADMIN_LOGIN_MAX_ATTEMPTS = int(env("ADMIN_LOGIN_MAX_ATTEMPTS", "10"))   # per IP per 15 minutes

# ───────────── Email (SMTP first, Gmail API over HTTPS as the fallback) ─────────────
# Render's free web services block outbound SMTP ports (25, 465, 587), so on Render the Gmail API is used instead.
EMAIL_BACKEND = env("EMAIL_BACKEND", "apps.web.mailer.FallbackEmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_USE_TLS = _bool("EMAIL_USE_TLS", "true")
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "").replace(" ", "")   # Gmail shows app passwords in groups of 4
EMAIL_TIMEOUT = int(env("EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "LenDen Saathi <%s>" % (env("EMAIL_HOST_USER", "no-reply@localhost") or "no-reply@localhost"))
EMAIL_OTP_TTL_SECONDS = 600
EMAIL_OTP_MAX_ATTEMPTS = 5
EMAIL_OTP_RESEND_SECONDS = int(env("EMAIL_OTP_RESEND_SECONDS", "45"))

# ───────────── Google (Drive documents + Gmail API fallback) ─────────────
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = env("GOOGLE_REFRESH_TOKEN", "")
GOOGLE_DRIVE_FOLDER_ID = env("GOOGLE_DRIVE_FOLDER_ID", "")
DOCUMENT_MAX_BYTES = 10 * 1024 * 1024
DOCUMENT_ALLOWED_EXTENSIONS = ("pdf", "png", "jpg", "jpeg", "docx", "xlsx", "txt", "csv")
