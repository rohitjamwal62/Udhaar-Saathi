"""Who is really calling? One place that decides the visitor's IP address, used by every rate limit.

Behind a load balancer (HAProxy, nginx, Render, Cloudflare) the TCP peer is the balancer, so the real address is read from
X-Forwarded-For. That header is a comma list in which every proxy appends the address it saw. The FIRST entry can be
written by the visitor, so it must not be trusted for rate limits: anyone could send "X-Forwarded-For: 1.2.3.4" and get a
fresh limit on every request.

Set TRUSTED_PROXY_COUNT to the number of proxies you control in front of the app (each appends one address):
    0  (default) keep the old behaviour: first entry. Kept so the current Render deployment does not change behaviour.
    1  one trusted proxy (the bundled HAProxy, which also overwrites the header): the LAST entry is the client.
    2  two trusted proxies (for example Cloudflare then HAProxy): the second from the last is the client.
"""
from django.conf import settings


def client_ip(request) -> str | None:
    parts = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
    trusted = int(getattr(settings, "TRUSTED_PROXY_COUNT", 0) or 0)
    if parts:
        if trusted > 0:
            return parts[-trusted] if len(parts) >= trusted else parts[0]
        return parts[0]
    return request.META.get("REMOTE_ADDR") or None
