import hashlib
import hmac
import json
import logging
from decimal import Decimal
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_scopes import scopes_disabled
from pretix.base.models import OrderPayment

from .models import ReferencedAuthorizeNetObject

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
@scopes_disabled()
def webhook(request, *args, **kwargs):
    # Always return 200 because AuthorizeNet just silently disables the webhook otherwise
    data = json.loads(request.body.decode())
    if data["payload"]["entityName"] != "transaction":
        return HttpResponse("Not interested.", status=200)

    try:
        ro = ReferencedAuthorizeNetObject.objects.get(reference=data["payload"]["id"])
    except ReferencedAuthorizeNetObject.DoesNotExist:
        # Far from perfect, but necessary for refund processing
        try:
            ro = ReferencedAuthorizeNetObject.objects.get(
                order__code=data["payload"]["invoiceNumber"].split("-")[0]
            )
        except ReferencedAuthorizeNetObject.DoesNotExist:
            logger.info(f"Received authorize.net webhook for unknown payment: {data}")
            return HttpResponse("Unknown payment.", status=200)

    provider = ro.payment.payment_provider

    received_signature = request.headers["X-Anet-Signature"].split("=")[-1].upper()
    computed_signature = (
        hmac.new(provider.settings.signature_key.encode(), request.body, hashlib.sha512)
        .hexdigest()
        .upper()
    )
    if received_signature != computed_signature:
        logger.info(f"Received authorize.net webhook with invalid signature: {data}")
        return HttpResponse("Invalid signature", status=200)

    ro.order.log_action("pretix_authorizenet.event", data=data)

    if data["eventType"] == "net.authorize.payment.void.created":
        ro.payment.create_external_refund(
            ro.payment.amount, info=json.dumps(data["payload"])
        )
    elif data["eventType"] == "net.authorize.payment.refund.created":
        ro.payment.create_external_refund(
            Decimal(data["payload"]["authAmount"]), info=json.dumps(data["payload"])
        )
    elif data[
        "eventType"
    ] == "net.authorize.payment.fraud.declined" and ro.payment.state not in (
        OrderPayment.PAYMENT_STATE_CONFIRMED,
        OrderPayment.PAYMENT_STATE_REFUNDED,
    ):
        ro.payment.fail()

    return HttpResponse("OK", status=200)
