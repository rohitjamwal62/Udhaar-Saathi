import uuid

from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.common.db import x
from apps.common.errors import ApiProblem

from .handlers import process_batch


class BatchSerializer(serializers.Serializer):
    device_id = serializers.UUIDField()
    items = serializers.ListField(child=serializers.DictField(), max_length=100)


class SyncBatchView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sync"

    def post(self, request):
        s = BatchSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        device_id = str(s.validated_data["device_id"])
        results = process_batch(request.user.id, device_id, s.validated_data["items"])
        return Response({"results": results, "cursor": str(uuid.uuid4().int % 10**12)})
