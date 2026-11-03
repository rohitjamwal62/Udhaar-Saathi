import logging

from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "apps.common"

    def ready(self):
        from django.conf import settings

        db = settings.DATABASES["default"]
        logging.getLogger("startup").info("Database: %s / %s (ssl=%s)", db.get("HOST"), db.get("NAME"),
                                          db.get("OPTIONS", {}).get("sslmode", "-"))
