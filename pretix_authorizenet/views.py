import hashlib
import hmac
import json
import logging
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
    data = json.loads(request.body.decode())
    print(data)
    if data["payload"]["entityName"] != "transaction":
        return HttpResponse("Not interested.", status_code=200)

    try:
        ro = ReferencedAuthorizeNetObject.objects.get(reference=data["payload"]["id"])
    except ReferencedAuthorizeNetObject.DoesNotExist:
        return HttpResponse("Unkown payment.", status_code=404)

    provider = ro.payment.payment_provider

    received_signature = request.headers["X-Anet-Signature"].split("=")[-1].upper()
    computed_signature = (
        hmac.new(provider.settings.signature_key.encode(), request.body, hashlib.sha512)
        .hexdigest()
        .upper()
    )
    if received_signature != computed_signature:
        return HttpResponse("Invalid signature", status_code=403)

    ro.order.log_action("pretix_authorizenet.event", data=data)

    if data["eventType"] in (
        "net.authorize.payment.refund.created",
        "net.authorize.payment.void.created",
    ):
        ro.payment.create_external_refund(ro.payment.amount)
    elif data[
        "eventType"
    ] == "net.authorize.payment.fraud.declined" and ro.payment.state not in (
        OrderPayment.PAYMENT_STATE_CONFIRMED,
        OrderPayment.PAYMENT_STATE_REFUNDED,
    ):
        ro.payment.fail()

    return HttpResponse("OK", status_code=200)


# {"notificationId":"c9864a20-1ef6-473c-b43f-828bc8ddb2cc","eventType":"net.authorize.payment.authcapture.created",
# "eventDate":"2022-07-14T10:54:09.6423514Z","webhookId":"10b37f1d-0e1e-4bc8-92b0-f75e74c27352","payload":
# {"responseCode":1,"authCode":"EXFG3O","avsResponse":"Y","authAmount":9.60,"merchantReferenceId":"E7QZP-P-1",
# "invoiceNumber":"E7QZP-P-1","entityName":"transaction","id":"40098176700"}}
