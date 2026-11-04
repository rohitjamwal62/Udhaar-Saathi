from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("web", "0003_ledger")]
    operations = [
        migrations.AddField("faq", "question_hi", models.CharField(
            blank=True, null=True, max_length=240, verbose_name="Question (Hindi)",
            help_text="Optional. Shown instead of the English question when the visitor chose Hindi.")),
        migrations.AddField("faq", "answer_hi", models.TextField(
            blank=True, null=True, verbose_name="Answer (Hindi)",
            help_text="Optional. Shown instead of the English answer when the visitor chose Hindi.")),
    ]
