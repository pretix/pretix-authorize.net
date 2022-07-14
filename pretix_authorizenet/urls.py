from django.conf.urls import url

from .views import webhook

urlpatterns = [
    url(r"^_authorizenet/webhook/$", webhook, name="webhook"),
]
