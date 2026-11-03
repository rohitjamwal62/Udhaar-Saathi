import logging

from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "apps.common"

    def ready(self):
        from django.conf import settings

        db = settings.DATABASES["default"]
        logging.getLogger("startup").info("Environment: %s | Database: %s / %s (ssl=%s)", settings.APP_ENV, db.get("HOST"), db.get("NAME"),
                                          db.get("OPTIONS", {}).get("sslmode", "-"))
