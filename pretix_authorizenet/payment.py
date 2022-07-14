import json
import logging
import requests
from collections import OrderedDict
from django import forms
from django.core.checks import messages
from django.http import HttpRequest
from django.template.loader import get_template
from django.utils.translation import gettext_lazy as _
from pretix.base.forms import SecretKeySettingsField
from pretix.base.models import Event, OrderPayment, OrderRefund
from pretix.base.payment import BasePaymentProvider, PaymentException
from pretix.base.settings import SettingsSandbox

from .models import ReferencedAuthorizeNetObject

logger = logging.getLogger(__name__)


class AuthorizeNetSettingsHolder(BasePaymentProvider):
    identifier = "authorizenet"
    verbose_name = _("Authorize.Net")
    is_enabled = False
    is_meta = True

    def __init__(self, event: Event):
        super().__init__(event)
        self.settings = SettingsSandbox("payment", "authorizenet", event)

    @property
    def test_mode_message(self):
        if self.settings.environment == "sandbox":
            return _(
                "The Authorize.Net module is running in sandbox mode. You can use a "
                '<a href="https://developer.authorize.net/hello_world/testing_guide.html">test card</a> to try out '
                "payments."
            )
        return None

    @property
    def settings_form_fields(self):
        fields = [
            (
                "environment",
                forms.ChoiceField(
                    label=_("Environment"),
                    initial="production",
                    choices=(
                        ("production", "Production"),
                        ("sandbox", "Sandbox"),
                    ),
                ),
            ),
            (
                "login_id",
                SecretKeySettingsField(
                    label=_("API Login ID"),
                ),
            ),
            (
                "transaction_key",
                SecretKeySettingsField(
                    label=_("Transaction Key"),
                ),
            ),
            (
                "public_client_key",
                forms.CharField(
                    # https://developer.authorize.net/api/reference/features/acceptjs.html#Generating_and_Using_the_Public_Client_Key
                    label=_("Public Client Key"),
                    help_text=_(
                        "To generate the Client Key, log in to the Merchant Interface as an Administrator and "
                        "navigate to Account > Settings > Security Settings > General Security Settings > Manage "
                        "Public Client Key. If the Public Client Key does not yet exist, answer your security "
                        "question to generate the key."
                    ),
                ),
            ),
        ]
        d = OrderedDict(
            fields
            + [
                (
                    "method_creditcard",
                    forms.BooleanField(
                        label=_("Credit card"),
                        required=True,
                        initial=True,
                    ),
                ),
            ]
            + list(super().settings_form_fields.items())
        )
        d.move_to_end("_enabled", last=False)
        return d


class AuthorizeNetMethod(BasePaymentProvider):
    method = ""
    abort_pending_allowed = False

    def __init__(self, event: Event):
        super().__init__(event)
        self.settings = SettingsSandbox("payment", "authorizenet", event)

    @property
    def settings_form_fields(self):
        return {}

    @property
    def identifier(self):
        return "authorizenet_{}".format(self.method)

    @property
    def is_enabled(self) -> bool:
        return self.settings.get("_enabled", as_type=bool) and self.settings.get(
            "method_{}".format(self.method), as_type=bool
        )

    @property
    def api_url(self):
        if self.settings.environment == "sandbox":
            return "https://apitest.authorize.net/xml/v1/request.api"
        return "https://api.authorize.net/xml/v1/request.api"

    def payment_refund_supported(self, payment: OrderPayment) -> bool:
        # Sources on the internet suggest that refunds are only possible for 90 days, which we could express through
        # return (now() - payment.payment_date).days <= 90
        # However I could not find a *trustworthy* source for this, so let's wait and see.
        return True

    def payment_partial_refund_supported(self, payment: OrderPayment) -> bool:
        return self.payment_refund_supported(payment)

    def payment_prepare(self, request, payment):
        return self.checkout_prepare(request, None)

    def checkout_prepare(self, request, cart):
        if not request.POST.get(f"authorizenet-{self.method}-datavalue"):
            messages.warning(
                request, _("You may need to enable JavaScript for Adyen payments.")
            )
            return False
        request.session[f"authorizenet_{self.method}_datavalue"] = request.POST.get(
            f"authorizenet-{self.method}-datavalue"
        )
        request.session[
            f"authorizenet_{self.method}_datadescriptor"
        ] = request.POST.get(f"authorizenet-{self.method}-datadescriptor")
        return True

    def payment_is_valid_session(self, request: HttpRequest):
        return request.session.get(
            f"authorizenet_{self.method}_datavalue"
        ) and request.session.get(f"authorizenet_{self.method}_datadescriptor")

    def payment_form_render(self, request) -> str:
        template = get_template("pretix_authorizenet/checkout_payment_form.html")
        ctx = {
            "request": request,
            "event": self.event,
            "settings": self.settings,
            "method": self.method,
        }
        return template.render(ctx)

    def checkout_confirm_render(self, request) -> str:
        template = get_template("pretix_authorizenet/checkout_payment_confirm.html")
        ctx = {
            "request": request,
            "event": self.event,
            "settings": self.settings,
            "provider": self,
        }
        return template.render(ctx)

    def payment_can_retry(self, payment):
        return self._is_still_available(order=payment.order)

    def payment_pending_render(self, request, payment) -> str:
        if payment.info:
            payment_info = json.loads(payment.info)
        else:
            payment_info = None
        template = get_template("pretix_authorizenet/pending.html")
        ctx = {
            "request": request,
            "event": self.event,
            "settings": self.settings,
            "provider": self,
            "order": payment.order,
            "payment": payment,
            "payment_info": payment_info,
        }
        return template.render(ctx)

    def payment_control_render(self, request, payment) -> str:
        if payment.info:
            payment_info = json.loads(payment.info)
        else:
            payment_info = None
        template = get_template("pretix_authorizenet/control.html")
        ctx = {
            "request": request,
            "event": self.event,
            "settings": self.settings,
            "payment_info": payment_info,
            "payment": payment,
            "method": self.method,
            "provider": self,
        }
        return template.render(ctx)

    def execute_refund(self, refund: OrderRefund, try_void=False):
        try:
            # Authorize.Net only allows a real "refund" if the transaction is already "settled", approx. 24h after
            # the payment. Before that, we can do a "void". So this function first tries the "refund", then, if the
            # appropriate error message has been received, it tries a "void" instead.
            if try_void:
                req = {
                    "transactionType": "voidTransaction",
                    "refTransId": refund.payment.info_data["transactionResponse"][
                        "transId"
                    ],
                }
            else:
                req = {
                    "transactionType": "refundTransaction",
                    "amount": str(refund.amount),
                    "currencyCode": self.event.currency,
                    "payment": {
                        "creditCard": {
                            "cardNumber": refund.payment.info_data[
                                "transactionResponse"
                            ]["accountNumber"][-4:],
                            "expirationDate": "XXXX",
                        }
                    },
                    "refTransId": refund.payment.info_data["transactionResponse"][
                        "transId"
                    ],
                    "order": {
                        "invoiceNumber": refund.full_id[:20],
                        "description": f"{refund.order.code} / {self.event}"[:255],
                    },
                }
            r = requests.post(
                self.api_url,
                json={
                    "createTransactionRequest": {
                        "merchantAuthentication": {
                            "name": self.settings.login_id,
                            "transactionKey": self.settings.transaction_key,
                        },
                        "refId": refund.full_id[:20],
                        "transactionRequest": req,
                    }
                },
            )
            r.raise_for_status()
            resp = json.loads(r.content.decode("utf-8-sig"))

            refund.info_data = resp
            refund.save(update_fields=["info"])
            if resp["messages"]["resultCode"] == "Ok":
                refund.info_data = resp
                refund.done()
                return True
            elif (
                resp.get("transactionResponse", {})
                .get("errors", [{}])[0]
                .get("errorCode")
                == "54"
                and not try_void
            ):
                return self.execute_refund(refund, try_void=True)
            else:
                refund.info_data = resp
                refund.state = OrderRefund.REFUND_STATE_FAILED
                refund.save()
                refund.order.log_action(
                    "pretix.event.order.refund.failed",
                    {
                        "local_id": refund.local_id,
                        "provider": refund.provider,
                        "message": ", ".join(
                            [
                                f"{msg['code']}: {msg['text']}"
                                for msg in resp["messages"]["message"]
                            ]
                            + [
                                f"{msg['errorCode']}: {msg['errorText']}"
                                for msg in resp.get("transactionResponse", {}).get(
                                    "errors", []
                                )
                            ]
                        ),
                    },
                )
                raise PaymentException(
                    ", ".join(
                        [
                            f"{msg['code']}: {msg['text']}"
                            for msg in resp["messages"]["message"]
                        ]
                        + [
                            f"{msg['errorCode']}: {msg['errorText']}"
                            for msg in resp.get("transactionResponse", {}).get(
                                "errors", []
                            )
                        ]
                    )
                )
        except requests.HTTPError as e:
            logger.exception("Failed to contact Authorize.Net")
            refund.info_data = {
                "error": True,
                "message": str(e),
            }
            refund.state = OrderRefund.REFUND_STATE_FAILED
            refund.save()
            refund.order.log_action(
                "pretix.event.order.refund.failed",
                {
                    "local_id": refund.local_id,
                    "provider": refund.provider,
                    "message": str(e),
                },
            )

            raise PaymentException(
                _("We were unable to contact Authorize.Net. Please try again later.")
            )

    def execute_payment(self, request: HttpRequest, payment: OrderPayment):
        try:
            r = requests.post(
                self.api_url,
                json={
                    "createTransactionRequest": {
                        "merchantAuthentication": {
                            "name": self.settings.login_id,
                            "transactionKey": self.settings.transaction_key,
                        },
                        "refId": payment.full_id[:20],
                        "transactionRequest": {
                            "transactionType": "authCaptureTransaction",
                            "amount": str(payment.amount),
                            "currencyCode": self.event.currency,
                            "payment": {
                                "opaqueData": {
                                    "dataDescriptor": request.session[
                                        f"authorizenet_{self.method}_datadescriptor"
                                    ],
                                    "dataValue": request.session[
                                        f"authorizenet_{self.method}_datavalue"
                                    ],
                                }
                            },
                            "order": {
                                "invoiceNumber": payment.full_id[:20],
                                "description": f"{payment.order.code} / {self.event}"[
                                    :255
                                ],
                            },
                            "poNumber": payment.order.code[:25],
                        },
                    }
                },
            )
            r.raise_for_status()
            resp = json.loads(r.content.decode("utf-8-sig"))

            payment.info_data = resp
            payment.save(update_fields=["info"])
            if resp["messages"]["resultCode"] == "Ok":
                ReferencedAuthorizeNetObject.objects.create(
                    order=payment.order,
                    payment=payment,
                    reference=resp["transactionResponse"]["transId"],
                )
                payment.info_data = resp
                payment.confirm()
                return
            else:
                payment.info_data = resp
                payment.state = OrderPayment.PAYMENT_STATE_FAILED
                payment.save()
                payment.order.log_action(
                    "pretix.event.order.payment.failed",
                    {
                        "local_id": payment.local_id,
                        "provider": payment.provider,
                        "message": ", ".join(
                            [
                                f"{msg['code']}: {msg['text']}"
                                for msg in resp["messages"]["message"]
                            ]
                            + [
                                f"{msg['errorCode']}: {msg['errorText']}"
                                for msg in resp.get("transactionResponse", {}).get(
                                    "errors", []
                                )
                            ]
                        ),
                    },
                )
                raise PaymentException(
                    ", ".join(
                        [
                            f"{msg['code']}: {msg['text']}"
                            for msg in resp["messages"]["message"]
                        ]
                        + [
                            f"{msg['errorCode']}: {msg['errorText']}"
                            for msg in resp.get("transactionResponse", {}).get(
                                "errors", []
                            )
                        ]
                    )
                )
        except requests.HTTPError as e:
            logger.exception("Failed to contact Authorize.Net")
            payment.info_data = {
                "error": True,
                "message": str(e),
            }
            payment.state = OrderPayment.PAYMENT_STATE_FAILED
            payment.save()
            payment.order.log_action(
                "pretix.event.order.payment.failed",
                {
                    "local_id": payment.local_id,
                    "provider": payment.provider,
                    "message": str(e),
                },
            )

            raise PaymentException(
                _("We were unable to contact Authorize.Net. Please try again later.")
            )

    def shred_payment_info(self, obj: OrderPayment):
        if not obj.info:
            return
        d = json.loads(obj.info)
        if "transactionResponse" in d:
            d["transactionResponse"] = {
                k: "█"
                for k in d["transactionResponse"].keys()
                if k
                not in (
                    "accountType",
                    "messages",
                    "transId",
                    "networkTransId",
                )
            }

        d["_shredded"] = True
        obj.info = json.dumps(d)
        obj.save(update_fields=["info"])


class AuthorizeNetCC(AuthorizeNetMethod):
    method = "creditcard"
    verbose_name = _("Credit card via Authorize.Net")
    public_name = _("Credit card")
