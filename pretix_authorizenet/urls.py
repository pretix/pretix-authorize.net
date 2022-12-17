from django.urls import path

from .views import webhook

urlpatterns = [
    path("_authorizenet/webhook/", webhook, name="webhook"),
]
