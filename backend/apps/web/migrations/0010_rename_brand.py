"""The product is now called LenDen Saathi: update the brand name in content that lives in the database."""
from django.db import migrations

OLD, NEW = "UdhaarSaathi", "LenDen Saathi"


def rename(apps, schema_editor):
    for model, fields in (("LegalPage", ("body_en", "body_hi")),
                          ("FAQ", ("question", "answer", "question_hi", "answer_hi"))):
        M = apps.get_model("web", model)
        for obj in M.objects.all():
            changed = []
            for f in fields:
                v = getattr(obj, f, "") or ""
                if OLD in v:
                    setattr(obj, f, v.replace(OLD, NEW))
                    changed.append(f)
            if changed:
                obj.save(update_fields=changed)
    # the plan name shown on the pricing page lives in the app's own table (created by database/create_tables.py)
    with schema_editor.connection.cursor() as cur:
        cur.execute("SELECT to_regclass('public.subscription_plans')")
        if cur.fetchone()[0]:
            cur.execute("UPDATE subscription_plans SET name = %s WHERE name = %s", [NEW, OLD])


class Migration(migrations.Migration):
    dependencies = [("web", "0009_fill_phone_norm")]
    operations = [migrations.RunPython(rename, migrations.RunPython.noop)]
