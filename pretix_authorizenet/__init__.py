from django.utils.translation import gettext_lazy

try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")

__version__ = "1.0.0"


class PluginApp(PluginConfig):
    name = "pretix_authorizenet"
    verbose_name = "Authorize.Net"

    class PretixPluginMeta:
        name = gettext_lazy("Authorize.Net")
        author = "pretix"
        description = gettext_lazy(
            "Accept credit card payments globally through your Authorize.Net account."
        )
        visible = True
        version = __version__
        category = "PAYMENT"
        compatibility = "pretix>=4.10.0"
        picture = "pretix_authorizenet/logo.png"

    def ready(self):
        from . import signals  # NOQA


default_app_config = "pretix_authorizenet.PluginApp"
