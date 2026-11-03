import logging
import uuid

log = logging.getLogger("request")


class RequestIdMiddleware:
    """Echo the app's X-Request-ID (or make one) so a request can be traced across logs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.request_id = rid[:64]
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response
