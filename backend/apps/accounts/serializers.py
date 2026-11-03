import re

from rest_framework import serializers

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_mobile(value: str) -> str | None:
    """Indian mobile numbers to E.164 (+91XXXXXXXXXX); other E.164 numbers are accepted as-is."""
    d = re.sub(r"[\s-]", "", value or "")
    if re.fullmatch(r"[6-9]\d{9}", d):
        return "+91" + d
    if re.fullmatch(r"91[6-9]\d{9}", d.lstrip("+")):
        return "+" + d.lstrip("+")
    return d if _E164.match(d) else None


class MobileField(serializers.CharField):
    def to_internal_value(self, data):
        m = normalize_mobile(super().to_internal_value(data))
        if not m:
            raise serializers.ValidationError("Enter a valid mobile number.")
        return m


def validate_password_strength(pw: str) -> str:
    if len(pw) < 8 or len(pw) > 128:
        raise serializers.ValidationError("Password must be 8 to 128 characters.")
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise serializers.ValidationError("Password must include letters and numbers.")
    if pw.lower() in {"password1", "password123", "12345678a", "qwerty123"}:
        raise serializers.ValidationError("That password is too common.")
    return pw


class SignupSerializer(serializers.Serializer):
    mobile = MobileField()
    name = serializers.CharField(max_length=120)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    role = serializers.ChoiceField(choices=["shopkeeper", "customer"])
    language = serializers.ChoiceField(choices=["en", "hi", "pa"], default="en")
    accepted_terms_version = serializers.CharField(max_length=20)

    def validate_password(self, v):
        return validate_password_strength(v)


class OtpRequestSerializer(serializers.Serializer):
    mobile = MobileField()
    purpose = serializers.ChoiceField(choices=["signup", "login", "recovery"])


class OtpVerifySerializer(serializers.Serializer):
    mobile = MobileField()
    challenge_id = serializers.CharField()
    otp = serializers.RegexField(r"^\d{6}$")
    device_id = serializers.UUIDField(required=False)


class LoginSerializer(serializers.Serializer):
    mobile = MobileField()
    password = serializers.CharField(trim_whitespace=False)
    device_id = serializers.UUIDField()


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class ForgotSerializer(serializers.Serializer):
    mobile = MobileField()


class ResetSerializer(serializers.Serializer):
    mobile = MobileField()
    challenge_id = serializers.CharField()
    otp = serializers.RegexField(r"^\d{6}$")
    new_password = serializers.CharField(trim_whitespace=False)

    def validate_new_password(self, v):
        return validate_password_strength(v)
