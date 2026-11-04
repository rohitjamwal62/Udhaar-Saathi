"""Copy the built-in contact email and the Terms / Privacy text into the database, so everything is editable in Django admin."""
from django.conf import settings
from django.db import migrations
from django.template.loader import render_to_string
from django.utils import timezone, translation


def seed(apps, schema_editor):
    SiteSetting = apps.get_model("web", "SiteSetting")
    LegalPage = apps.get_model("web", "LegalPage")
    if not SiteSetting.objects.exists():
        SiteSetting.objects.create(support_email=settings.SUPPORT_EMAIL)
    ctx = {"SITE_NAME": settings.SITE_NAME, "SUPPORT_EMAIL": settings.SUPPORT_EMAIL, "YEAR": timezone.now().year}
    for slug in ("terms", "privacy"):
        page, created = LegalPage.objects.get_or_create(slug=slug)
        if not created and (page.body_en.strip() or page.body_hi.strip()):
            continue                                   # never overwrite text an admin already edited
        for lang, field in (("en", "body_en"), ("hi", "body_hi")):
            with translation.override(lang):
                setattr(page, field, render_to_string(f"web/_{slug}_body.html", ctx).strip())
        page.save()


class Migration(migrations.Migration):
    dependencies = [("web", "0006_site_settings_legal_pages")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
