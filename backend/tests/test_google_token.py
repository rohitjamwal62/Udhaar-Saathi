"""The Google refresh token is saved after every refresh and read back next time (database by default, JSON file optionally)."""
import json
import os
from unittest import mock

import pytest
from django.test import Client, override_settings

from apps.web import google, google_token
from apps.web.models import GoogleToken

CREDS = dict(GOOGLE_CLIENT_ID="cid", GOOGLE_CLIENT_SECRET="csecret", GOOGLE_REFRESH_TOKEN="env-token-1", GOOGLE_TOKEN_FILE="")


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body if body is not None else {}
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._body


def _ok(access="access-A", **extra):
    return _Resp(200, {"access_token": access, "expires_in": 3599, "scope": "s", "token_type": "Bearer", **extra})


def _fresh():
    """Forget the cached access token so the next call really refreshes."""
    google._token.update(value="", exp=0.0)


@pytest.fixture(autouse=True)
def _clean_cache():
    _fresh()
    yield
    _fresh()


def _used_tokens(post):
    return [c.kwargs["data"]["refresh_token"] for c in post.call_args_list]


# ───────────── the structure: read -> use -> save, every time ─────────────
@override_settings(**CREDS)
def test_first_refresh_uses_the_setting_and_saves_it():
    assert not GoogleToken.objects.exists()
    with mock.patch.object(google.requests, "post", return_value=_ok()) as post:
        assert google.access_token() == "access-A"
    assert _used_tokens(post) == ["env-token-1"]
    row = GoogleToken.objects.get()
    assert row.refresh_token == "env-token-1" and row.rotations == 0 and row.seed_hash == google_token.fingerprint("env-token-1")


@override_settings(**CREDS)
def test_when_google_sends_a_new_refresh_token_it_replaces_the_old_one_and_is_used_next_time():
    with mock.patch.object(google.requests, "post", return_value=_ok(refresh_token="env-token-2")) as post:
        google.access_token()
    row = GoogleToken.objects.get()
    assert row.refresh_token == "env-token-2" and row.rotations == 1                      # replaced, counted
    _fresh()
    with mock.patch.object(google.requests, "post", return_value=_ok("access-B", refresh_token="env-token-3")) as post2:
        assert google.access_token() == "access-B"
    assert _used_tokens(post2) == ["env-token-2"]                                         # the replacement was read back and used
    row.refresh_from_db()
    assert row.refresh_token == "env-token-3" and row.rotations == 2 and GoogleToken.objects.count() == 1


@override_settings(**CREDS)
def test_when_google_sends_no_new_token_the_same_one_is_kept_and_nothing_is_counted():
    for _ in range(3):
        _fresh()
        with mock.patch.object(google.requests, "post", return_value=_ok()) as post:
            google.access_token()
        assert _used_tokens(post) == ["env-token-1"]                                      # what Google does in practice
    row = GoogleToken.objects.get()
    assert (row.refresh_token, row.rotations) == ("env-token-1", 0) and GoogleToken.objects.count() == 1


@override_settings(**CREDS)
def test_a_cached_access_token_is_reused_without_calling_google_again():
    with mock.patch.object(google.requests, "post", return_value=_ok()) as post:
        google.access_token(); google.access_token(); google.access_token()
    assert post.call_count == 1


# ───────────── a re-consent always wins over an older saved copy ─────────────
def test_changing_the_setting_after_a_new_consent_overrides_the_saved_token():
    with override_settings(**CREDS):
        with mock.patch.object(google.requests, "post", return_value=_ok(refresh_token="rotated-old")):
            google.access_token()
        assert GoogleToken.objects.get().refresh_token == "rotated-old"
    _fresh()
    with override_settings(**{**CREDS, "GOOGLE_REFRESH_TOKEN": "brand-new-consent"}):
        with mock.patch.object(google.requests, "post", return_value=_ok()) as post:
            google.access_token()
        assert _used_tokens(post) == ["brand-new-consent"]                                # NOT the stale saved one
        row = GoogleToken.objects.get()
        assert row.refresh_token == "brand-new-consent" and row.rotations == 0 and GoogleToken.objects.count() == 1


# ───────────── safety nets ─────────────
@override_settings(**CREDS)
def test_if_the_saved_token_is_refused_it_falls_back_to_the_setting_and_heals_the_store():
    GoogleToken.objects.create(refresh_token="saved-but-bad", seed_hash=google_token.fingerprint("env-token-1"), rotations=1)
    bad = _Resp(400, {"error": "invalid_grant"})
    with mock.patch.object(google.requests, "post", side_effect=[bad, _ok()]) as post:
        assert google.access_token() == "access-A"
    assert _used_tokens(post) == ["saved-but-bad", "env-token-1"]
    assert GoogleToken.objects.get().refresh_token == "env-token-1"


@override_settings(**CREDS)
def test_when_every_token_is_refused_the_clear_reconnect_message_is_kept():
    GoogleToken.objects.create(refresh_token="saved", seed_hash=google_token.fingerprint("env-token-1"), rotations=1)
    with mock.patch.object(google.requests, "post", return_value=_Resp(400, {"error": "invalid_grant"})):
        with pytest.raises(google.GoogleError, match="connect Google again"):
            google.access_token()


@override_settings(**CREDS)
def test_a_broken_store_never_stops_email_or_drive():
    with mock.patch.object(google_token, "store", side_effect=RuntimeError("database is down")):
        with mock.patch.object(google.requests, "post", return_value=_ok(refresh_token="new-one")) as post:
            assert google.access_token() == "access-A"                                    # still works from the setting
    assert _used_tokens(post) == ["env-token-1"]


@override_settings(**CREDS)
def test_other_errors_are_not_retried_and_nothing_is_saved():
    with mock.patch.object(google.requests, "post", return_value=_Resp(500, {})) as post:
        with pytest.raises(google.GoogleError):
            google.access_token()
    assert post.call_count == 1 and not GoogleToken.objects.exists()


@override_settings(**{**CREDS, "GOOGLE_REFRESH_TOKEN": ""})
def test_without_any_token_it_says_google_is_not_connected():
    with pytest.raises(google.GoogleError, match="not connected"):
        google.access_token()


# ───────────── the optional JSON file ─────────────
def test_a_json_file_is_written_read_back_and_replaced(tmp_path):
    path = tmp_path / "google_token.json"
    with override_settings(**{**CREDS, "GOOGLE_TOKEN_FILE": str(path)}):
        with mock.patch.object(google.requests, "post", return_value=_ok(refresh_token="file-token-2")):
            google.access_token()
        data = json.loads(path.read_text())
        assert data["refresh_token"] == "file-token-2" and data["rotations"] == 1
        assert set(data) == {"refresh_token", "seed_hash", "rotations", "updated_at"}
        assert not GoogleToken.objects.exists()                                           # the file replaces the database store
        _fresh()
        with mock.patch.object(google.requests, "post", return_value=_ok(refresh_token="file-token-3")) as post:
            google.access_token()
        assert _used_tokens(post) == ["file-token-2"]                                     # read back from the file
        assert json.loads(path.read_text())["refresh_token"] == "file-token-3"            # and replaced
        assert [p.name for p in tmp_path.iterdir()] == ["google_token.json"]              # no temp files left behind


def test_a_corrupt_json_file_is_ignored_and_the_setting_is_used(tmp_path):
    path = tmp_path / "google_token.json"
    path.write_text("{ this is not json")
    with override_settings(**{**CREDS, "GOOGLE_TOKEN_FILE": str(path)}):
        with mock.patch.object(google.requests, "post", return_value=_ok()) as post:
            assert google.access_token() == "access-A"
        assert _used_tokens(post) == ["env-token-1"]
        assert json.loads(path.read_text())["refresh_token"] == "env-token-1"             # repaired by the next save


def test_the_json_file_follows_a_re_consent_too(tmp_path):
    path = tmp_path / "google_token.json"
    with override_settings(**{**CREDS, "GOOGLE_TOKEN_FILE": str(path)}):
        with mock.patch.object(google.requests, "post", return_value=_ok(refresh_token="stale")):
            google.access_token()
    _fresh()
    with override_settings(**{**CREDS, "GOOGLE_REFRESH_TOKEN": "after-reconsent", "GOOGLE_TOKEN_FILE": str(path)}):
        with mock.patch.object(google.requests, "post", return_value=_ok()) as post:
            google.access_token()
        assert _used_tokens(post) == ["after-reconsent"]


# ───────────── the token itself is never exposed ─────────────
def test_the_admin_diagnostics_show_where_the_token_lives_but_never_the_token():
    from django.contrib.auth import get_user_model
    get_user_model().objects.create_superuser("Boss", "boss@example.com", "Test-Admin-Pass-1")
    c = Client(); c.login(username="Boss", password="Test-Admin-Pass-1")
    with override_settings(**CREDS):
        with mock.patch.object(google.requests, "post", return_value=_ok(refresh_token="SUPER-SECRET-TOKEN")):
            google.access_token()
        with mock.patch("apps.web.diagnostics.socket.create_connection", side_effect=OSError("blocked")), \
                mock.patch.object(google.requests, "get", return_value=_Resp(200, {"scope": "x"})):
            body = c.get("/admin/email-check/").content.decode()
    data = json.loads(body)
    assert data["google_token_store"] == {"stored_in": "database", "saved_token_exists": True, "replaced_by_google_times": 1,
                                          "last_saved_at": data["google_token_store"]["last_saved_at"]}
    assert "SUPER-SECRET-TOKEN" not in body and "env-token-1" not in body


def test_the_token_is_never_written_to_the_log(caplog):
    with override_settings(**CREDS), caplog.at_level("DEBUG"):
        with mock.patch.object(google.requests, "post", return_value=_ok(refresh_token="LOGGED-SECRET")):
            google.access_token()
    assert "LOGGED-SECRET" not in caplog.text and "env-token-1" not in caplog.text


def test_the_admin_does_not_offer_the_token_table():
    from django.contrib import admin
    assert GoogleToken not in admin.site._registry
