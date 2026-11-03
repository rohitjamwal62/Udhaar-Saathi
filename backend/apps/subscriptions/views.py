import json
import logging

from django.conf import settings
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.common.db import atomic, q, q1, x
from apps.common.errors import ApiProblem
from apps.shops.access import shop_for_user

from . import service
from .gateway import get_gateway

log = logging.getLogger("payments")


def _info(shop_id: str) -> dict:
    sub = service.refresh(shop_id)
    if not sub:
        raise ApiProblem("No subscription for this shop yet.", "not_found", 404)
    plan = q1("SELECT code, amount_paise, billing_interval FROM subscription_plans WHERE id = %s", [sub["plan_id"]])
    return {
        "status": sub["status"], "plan_code": plan["code"], "amount_paise": plan["amount_paise"],
        "billing_interval": plan["billing_interval"], "trial_ends_at": sub["trial_ends_at"],
        "current_period_end": sub["current_period_end"], "grace_ends_at": sub["grace_ends_at"],
        "cancel_at_period_end": sub["cancel_at_period_end"], "taxes_note": settings.TAXES_NOTE,
    }


class CurrentView(APIView):
    def get(self, request):
        return Response(_info(str(shop_for_user(request.user.id)["id"])))


class PaymentsView(APIView):
    def get(self, request):
        shop = shop_for_user(request.user.id)
        rows = q("""SELECT p.id, p.amount_paise, p.status, p.method, p.created_at, i.invoice_number
                      FROM payments p JOIN payment_orders o ON o.id = p.order_id
                      JOIN subscriptions s ON s.id = o.subscription_id
                      LEFT JOIN subscription_invoices i ON i.payment_id = p.id
                     WHERE s.shop_id = %s ORDER BY p.created_at DESC LIMIT 100""", [shop["id"]])
        return Response({"results": [{"id": str(r["id"]), "amount_paise": r["amount_paise"], "status": r["status"],
                                      "method": r["method"], "created_at": r["created_at"], "invoice_url": None,
                                      "invoice_number": r["invoice_number"]} for r in rows]})


class OrderSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=120)


class OrdersView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        s = OrderSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        shop = shop_for_user(request.user.id)
        sub = service.refresh(shop["id"])
        if not sub:
            raise ApiProblem("No subscription for this shop yet.", "not_found", 404)
        if sub["status"] == "SUSPENDED":
            raise ApiProblem("This account is suspended. Please contact support.", "suspended", 403)
        key = f"{shop['id']}:{s.validated_data['idempotency_key']}"
        gw = get_gateway()
        existing = q1("SELECT * FROM payment_orders WHERE idempotency_key = %s AND subscription_id = %s", [key, sub["id"]])
        if not existing:
            plan = q1("SELECT amount_paise FROM subscription_plans WHERE id = %s", [sub["plan_id"]])
            amount = plan["amount_paise"]  # the server decides the amount, never the client
            order_id = gw.create_order(amount, f"sub_{str(sub['id'])[:8]}")
            existing = q1(
                """INSERT INTO payment_orders(subscription_id, gateway, gateway_order_id, amount_paise, idempotency_key)
                   VALUES (%s,%s,%s,%s,%s) ON CONFLICT (idempotency_key) DO NOTHING RETURNING *""",
                [sub["id"], gw.name, order_id, amount, key])
            if not existing:
                existing = q1("SELECT * FROM payment_orders WHERE idempotency_key = %s", [key])
        return Response({"order_id": existing["gateway_order_id"], "key_id": gw.key_id(),
                         "amount_paise": existing["amount_paise"], "currency": existing["currency"].strip()})


class VerifySerializer(serializers.Serializer):
    order_id = serializers.CharField(max_length=80)
    payment_id = serializers.CharField(max_length=80)
    signature = serializers.CharField(max_length=256)


class VerifyView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        s = VerifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        shop = shop_for_user(request.user.id)
        order = q1("""SELECT o.* FROM payment_orders o JOIN subscriptions s ON s.id = o.subscription_id
                       WHERE o.gateway_order_id = %s AND s.shop_id = %s""", [d["order_id"], shop["id"]])
        if not order:
            raise ApiProblem("Order not found.", "not_found", 404)
        if not get_gateway().verify_payment_signature(d["order_id"], d["payment_id"], d["signature"]):
            service.audit(order["subscription_id"], str(request.user.id), "payment_signature_invalid", None, None,
                          f"order {d['order_id']}")
            raise ApiProblem("Payment could not be verified.", "invalid_signature", 400)
        with atomic():
            service.apply_payment_success(order, d["payment_id"], None, order["amount_paise"])
        return Response({"status": _info(str(shop["id"]))["status"]})


class CancelView(APIView):
    def post(self, request):
        shop = shop_for_user(request.user.id)
        sub = service.refresh(shop["id"])
        if not sub:
            raise ApiProblem("No subscription for this shop yet.", "not_found", 404)
        if not sub["cancel_at_period_end"]:
            x("UPDATE subscriptions SET cancel_at_period_end = TRUE, updated_at = now() WHERE id = %s", [sub["id"]])
            service.audit(sub["id"], str(request.user.id), "renewal_canceled", sub["status"], sub["status"])
        return Response(_info(str(shop["id"])))


class RazorpayWebhookView(APIView):
    """Signed server-to-server events. Duplicate and out-of-order deliveries are tolerated."""
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "webhook"

    def post(self, request):
        body = request.body
        sig = request.headers.get("X-Razorpay-Signature", "")
        event_id = request.headers.get("X-Razorpay-Event-Id", "")
        valid = get_gateway().verify_webhook(body, sig)
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            return Response({"detail": "Bad payload"}, status=400)
        if not valid:
            log.warning("razorpay webhook with invalid signature")
            return Response({"detail": "Invalid signature"}, status=400)
        if not event_id:
            return Response({"detail": "Missing event id"}, status=400)
        etype = str(payload.get("event", ""))[:60]
        with atomic():
            fresh = x("""INSERT INTO gateway_webhook_events(event_id, event_type, signature_valid, payload)
                         VALUES (%s,%s,TRUE,%s) ON CONFLICT (gateway, event_id) DO NOTHING""",
                      [event_id, etype, json.dumps(payload)]) == 1
            if not fresh:
                return Response({"status": "duplicate"})
            handled = self._handle(etype, payload)
            if handled:
                x("UPDATE gateway_webhook_events SET processed_at = now() WHERE event_id = %s", [event_id])
        return Response({"status": "ok" if handled else "ignored"})

    def _handle(self, etype: str, payload: dict) -> bool:
        ent = (payload.get("payload", {}).get("payment") or {}).get("entity") or {}
        refund = (payload.get("payload", {}).get("refund") or {}).get("entity") or {}
        payment_id = ent.get("id") or refund.get("payment_id")
        order_id = ent.get("order_id")
        if etype == "payment.captured" and payment_id and order_id:
            order = q1("SELECT * FROM payment_orders WHERE gateway_order_id = %s", [order_id])
            if not order or ent.get("amount") != order["amount_paise"]:
                return False  # unknown order or amount mismatch: stored, never applied
            service.apply_payment_success(order, payment_id, ent.get("method"), order["amount_paise"])
            return True
        if etype == "payment.failed" and payment_id and order_id:
            order = q1("SELECT * FROM payment_orders WHERE gateway_order_id = %s", [order_id])
            if not order:
                return False
            x("""INSERT INTO payments(order_id, gateway_payment_id, amount_paise, status, method, failure_code)
                 VALUES (%s,%s,%s,'failed',%s,%s) ON CONFLICT (gateway_payment_id) DO NOTHING""",
              [order["id"], payment_id, order["amount_paise"], ent.get("method"), str(ent.get("error_code") or "")[:80]])
            service.audit(order["subscription_id"], "webhook", "payment_failed", None, None, str(ent.get("error_code")))
            return True
        if etype in ("refund.processed", "payment.refunded") and payment_id:
            n = x("UPDATE payments SET status='refunded' WHERE gateway_payment_id = %s AND status = 'success'", [payment_id])
            x("""UPDATE subscription_invoices SET status='refunded'
                  WHERE payment_id = (SELECT id FROM payments WHERE gateway_payment_id = %s)""", [payment_id])
            return bool(n)
        return False
