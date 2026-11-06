"""Running more than one copy of the app behind a load balancer: client address, shared cache, pooled database settings."""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
from django.test import Client, RequestFactory, override_settings

from apps.common import ratelimit
from apps.common.net import client_ip

BACKEND = Path(__file__).resolve().parents[1]


def _req(xff=None, remote="10.0.0.9"):
    meta = {"REMOTE_ADDR": remote}
    if xff is not None:
        meta["HTTP_X_FORWARDED_FOR"] = xff
    return RequestFactory().get("/", **meta)


# ───────────── the visitor's address ─────────────
def test_default_keeps_the_old_behaviour_first_entry_then_remote_addr():
    assert client_ip(_req("1.1.1.1, 2.2.2.2")) == "1.1.1.1"
    assert client_ip(_req(None, remote="7.7.7.7")) == "7.7.7.7"
    assert client_ip(_req("")) == "10.0.0.9"


@override_settings(TRUSTED_PROXY_COUNT=1)
def test_with_one_trusted_proxy_a_forged_first_entry_is_ignored():
    # the visitor sends "9.9.9.9"; the proxy appends the address it really saw
    assert client_ip(_req("9.9.9.9, 203.0.113.5")) == "203.0.113.5"
    assert client_ip(_req("203.0.113.5")) == "203.0.113.5"            # the bundled HAProxy overwrites the header with one value


@override_settings(TRUSTED_PROXY_COUNT=2)
def test_with_two_trusted_proxies_the_address_the_first_proxy_saw_is_used():
    assert client_ip(_req("forged, 203.0.113.5, 172.16.0.2")) == "203.0.113.5"
    assert client_ip(_req("203.0.113.5")) == "203.0.113.5"            # fewer entries than proxies: fall back to the first


@override_settings(TRUSTED_PROXY_COUNT=1, ADMIN_LOGIN_MAX_ATTEMPTS=2)
def test_a_forged_forwarded_header_does_not_reset_the_admin_login_limit():
    c = Client()
    codes = []
    for i in range(4):
        r = c.post("/admin/login/", {"username": "x", "password": "y"}, HTTP_X_FORWARDED_FOR=f"6.6.6.{i}, 203.0.113.50")
        codes.append(r.status_code)
    assert codes[:2] != [429, 429] and 429 in codes[2:]              # the 3rd and 4th attempts are blocked, whatever the first entry says


# ───────────── the rate limiter and the shared cache ─────────────
def test_rate_limit_counts_per_key_and_blocks_after_the_limit():
    results = [ratelimit.hit("scaling:test", 3, 60) for _ in range(5)]
    assert results == [True, True, True, False, False]
    assert ratelimit.hit("scaling:other", 3, 60) is True


def test_rate_limit_lets_requests_through_when_the_shared_cache_is_down(caplog):
    with mock.patch.object(ratelimit.cache, "add", side_effect=ConnectionError("redis is down")):
        with caplog.at_level("WARNING", logger="ratelimit"):
            assert ratelimit.hit("scaling:down", 1, 60) is True
            assert ratelimit.hit("scaling:down", 1, 60) is True       # open, not an outage for everybody
    assert "cache unavailable" in caplog.text


# ───────────── settings read from the environment (checked in a fresh interpreter) ─────────────
def _settings_with(**env_overrides) -> dict:
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings", "USE_LOCAL_DB": "1", "DATABASE_URL": "",
           "DJANGO_DEBUG": "true", "REDIS_URL": "", "TRUSTED_PROXY_COUNT": "", "DB_POOLED": "", **env_overrides}
    code = ("import json,django;django.setup();from django.conf import settings as s;"
            "print(json.dumps({'cache':s.CACHES['default']['BACKEND'],'session':getattr(s,'SESSION_ENGINE',''),"
            "'proxies':s.TRUSTED_PROXY_COUNT,'drf':s.REST_FRAMEWORK.get('NUM_PROXIES'),"
            "'conn_max_age':s.DATABASES['default'].get('CONN_MAX_AGE'),'cursors':s.DATABASES['default'].get('DISABLE_SERVER_SIDE_CURSORS')}))")
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-600:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_defaults_are_unchanged_for_a_single_instance():
    s = _settings_with()
    assert s["cache"].endswith("LocMemCache") and s["proxies"] == 0 and s["drf"] is None
    assert s["conn_max_age"] == 60 and not s["cursors"]
    assert "cached_db" not in s["session"]


def test_redis_url_switches_to_a_shared_cache_and_cached_sessions():
    s = _settings_with(REDIS_URL="redis://redis:6379/0")
    assert s["cache"].endswith("RedisCache") and s["session"].endswith("cached_db")


def test_trusted_proxy_count_reaches_both_django_and_drf():
    s = _settings_with(TRUSTED_PROXY_COUNT="2")
    assert s["proxies"] == 2 and s["drf"] == 2


def test_db_pooled_turns_off_connection_reuse_for_a_transaction_pooler():
    s = _settings_with(DB_POOLED="1")
    assert s["conn_max_age"] == 0 and s["cursors"] is True


@pytest.mark.skipif(not os.environ.get("REDIS_TEST_URL"), reason="set REDIS_TEST_URL to run the real-Redis check")
def test_rate_limit_is_shared_through_a_real_redis():
    """Optional integration check: two separate cache handles see the same counter."""
    from django.core.cache.backends.redis import RedisCache
    url = os.environ["REDIS_TEST_URL"]
    a, b = RedisCache(url, {"KEY_PREFIX": "t"}), RedisCache(url, {"KEY_PREFIX": "t"})
    a.delete("shared"); a.add("shared", 0, 30)
    a.incr("shared"); b.incr("shared")
    assert a.get("shared") == 2
