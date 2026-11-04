from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameBackend(ModelBackend):
    """Log in with either the email address or the username (the Django admin superuser uses a username)."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        if not username or not password:
            return None
        user = User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).order_by("id").first()
        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
