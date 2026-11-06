import logging

from django.core.cache import cache

from .errors import ApiProblem

log = logging.getLogger("ratelimit")


def hit(key: str, limit: int, window_seconds: int) -> bool:
    """Count one event. Returns True while still under the limit (fixed window).

    If the shared cache (Redis) is briefly unreachable the request is let through and the problem is logged: a cache
    outage must not log everybody out of the site. (Login and OTP are still protected by their own per-account checks.)
    """
    try:
        cache.add(key, 0, window_seconds)
        try:
            return cache.incr(key) <= limit
        except ValueError:  # key expired between add and incr
            cache.set(key, 1, window_seconds)
            return True
    except Exception:  # noqa: BLE001  (redis.exceptions.ConnectionError and friends)
        log.warning("rate-limit cache unavailable; letting the request through", exc_info=True)
        return True


def check(key: str, limit: int, window_seconds: int, message: str = "Too many attempts. Please try again later."):
    if not hit(key, limit, window_seconds):
        raise ApiProblem(message, "rate_limited", 429)
