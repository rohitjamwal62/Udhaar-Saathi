"""Create or update the Django admin superuser.

    python manage.py create_site_admin --username Rohit --email a@b.c --password-env ADMIN_PASSWORD
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create (or update) a superuser. The password is read from an environment variable, never from the command line."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--first-name", default="")
        parser.add_argument("--password-env", default="ADMIN_PASSWORD")

    def handle(self, *args, **opts):
        pw = os.environ.get(opts["password_env"], "")
        if not pw:
            raise CommandError(f"Set the {opts['password_env']} environment variable first.")
        User = get_user_model()
        user = User.objects.filter(username__iexact=opts["username"]).first() or User(username=opts["username"])
        created = user.pk is None
        user.email, user.first_name = opts["email"].lower(), opts["first_name"] or opts["username"]
        user.is_staff = user.is_superuser = user.is_active = True
        user.set_password(pw)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"{'Created' if created else 'Updated'} superuser '{user.username}' <{user.email}>"))
