from django.apps import AppConfig


class LegacyConfig(AppConfig):
    name = "apps.legacy"
    label = "legacy"
    verbose_name = "App database (tables from create_tables.py)"
