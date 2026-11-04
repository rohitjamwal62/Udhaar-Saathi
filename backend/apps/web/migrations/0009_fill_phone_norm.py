"""Fill the 10-digit match key for people added before customer accounts could be linked."""
import re

from django.db import migrations


def digits(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d if re.fullmatch(r"[6-9]\d{9}", d) else ""


def fill(apps, schema_editor):
    Party = apps.get_model("web", "Party")
    for p in Party.objects.exclude(phone="").iterator():
        n = digits(p.phone)
        if n != p.phone_norm:
            Party.objects.filter(pk=p.pk).update(phone_norm=n)


class Migration(migrations.Migration):
    dependencies = [("web", "0008_customer_links_and_proofs")]
    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
