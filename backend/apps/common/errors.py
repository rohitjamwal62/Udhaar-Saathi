from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler


class ApiProblem(APIException):
    """Raise anywhere in a view to return {"detail": message, "code": code} with a status."""

    def __init__(self, message: str, code: str = "error", http_status: int = status.HTTP_400_BAD_REQUEST):
        self.status_code = http_status
        super().__init__(detail=message, code=code)


def _first_message(data) -> str:
    if isinstance(data, dict):
        for k, v in data.items():
            msg = _first_message(v)
            return msg if k in ("detail", "non_field_errors") else f"{k}: {msg}"
    if isinstance(data, (list, tuple)) and data:
        return _first_message(data[0])
    return str(data)


def exception_handler(exc, context):
    resp = drf_handler(exc, context)
    if resp is None:
        return None
    if isinstance(exc, ValidationError):
        return Response(
            {"detail": _first_message(resp.data), "code": "validation_error", "errors": resp.data},
            status=resp.status_code,
        )
    if isinstance(resp.data, dict) and "detail" in resp.data:
        code = getattr(getattr(exc, "detail", None), "code", None) or "error"
        return Response({"detail": str(resp.data["detail"]), "code": code}, status=resp.status_code)
    return resp
