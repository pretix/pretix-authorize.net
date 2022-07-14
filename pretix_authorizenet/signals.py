import logging

from django.dispatch import receiver
from django.http import HttpRequest, HttpResponse
from django.template.loader import get_template
from django.urls import resolve

from pretix.base.middleware import _parse_csp, _merge_csp, _render_csp
from pretix.base.signals import register_payment_providers
from pretix.presale.signals import html_head, process_response

logger = logging.getLogger(__name__)


@receiver(register_payment_providers, dispatch_uid="payment_authorizenet")
def register_payment_provider(sender, **kwargs):
    from .payment import AuthorizeNetSettingsHolder, AuthorizeNetCC

    return [AuthorizeNetSettingsHolder, AuthorizeNetCC]


@receiver(html_head, dispatch_uid="payment_authorizenet_html_head")
def html_head_presale(sender, request=None, **kwargs):
    from .payment import AuthorizeNetMethod

    provider = AuthorizeNetMethod(sender)
    url = resolve(request.path_info)
    if provider.settings.get('_enabled', as_type=bool) and (("checkout" in url.url_name and url.kwargs.get("step") == "payment") or "order.pay" in url.url_name):
        template = get_template('pretix_authorizenet/presale_head.html')
        ctx = {
            'environment': provider.settings.environment,
            'login_id': provider.settings.login_id,
            'public_client_key': provider.settings.public_client_key,
        }
        return template.render(ctx)
    else:
        return ""


@receiver(signal=process_response, dispatch_uid="payment_authorizenet_middleware_resp")
def signal_process_response(sender, request: HttpRequest, response: HttpResponse, **kwargs):
    from .payment import AuthorizeNetSettingsHolder

    provider = AuthorizeNetSettingsHolder(sender)
    url = resolve(request.path_info)

    if provider.settings.get('_enabled', as_type=bool) and ("checkout" in url.url_name or "order.pay" in url.url_name):
        if 'Content-Security-Policy' in response:
            h = _parse_csp(response['Content-Security-Policy'])
        else:
            h = {}
        csps = {}

        if provider.settings.environment == 'sandbox':
            csps['script-src'] = ['https://jstest.authorize.net']
            csps['frame-src'] = ['https://jstest.authorize.net']
        else:
            csps['script-src'] = ['https://js.authorize.net']
            csps['frame-src'] = ['https://js.authorize.net']

        # Authorize.Net unfortunately applies styles through their script-src
        # Also, the unsafe-inline needs to specified within single quotes!
        csps['style-src'] = ["'unsafe-inline'"]

        _merge_csp(h, csps)

        if h:
            response['Content-Security-Policy'] = _render_csp(h)
    return response
