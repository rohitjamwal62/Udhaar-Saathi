"""Send one real test email:   python manage.py test_email you@example.com"""
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from apps.web import google
from apps.web.mailer import FallbackEmailBackend


class Command(BaseCommand):
    help = "Sends a test message and reports whether SMTP or the Gmail API carried it."

    def add_arguments(self, parser):
        parser.add_argument("to")

    def handle(self, *args, **opts):
        self.stdout.write(f"backend={settings.EMAIL_BACKEND.rsplit('.', 1)[-1]} smtp_user={settings.EMAIL_HOST_USER or '-'} google_connected={google.configured()}")
        n = send_mail("LenDen Saathi test email", "This is a test email from LenDen Saathi. If you can read it, email delivery works.",
                      settings.DEFAULT_FROM_EMAIL, [opts["to"]], fail_silently=False)
        self.stdout.write(self.style.SUCCESS(f"sent={n} via={FallbackEmailBackend.last_transport or 'configured backend'}"))
