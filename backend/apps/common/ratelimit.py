from django.core.cache import cache

from .errors import ApiProblem


def hit(key: str, limit: int, window_seconds: int) -> bool:
    """Count one event. Returns True while still under the limit (fixed window)."""
    cache.add(key, 0, window_seconds)
    try:
        return cache.incr(key) <= limit
    except ValueError:  # key expired between add and incr
        cache.set(key, 1, window_seconds)
        return True


def check(key: str, limit: int, window_seconds: int, message: str = "Too many attempts. Please try again later."):
    if not hit(key, limit, window_seconds):
        raise ApiProblem(message, "rate_limited", 429)
