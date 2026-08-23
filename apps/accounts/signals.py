from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from apps.core.audit import AuditAction, record


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs):
    record(
        AuditAction.LOGIN,
        actor=user,
        request=request,
        obj=user,
        summary=f"{user.display_name} signed in as {user.get_role_display().lower()}",
    )


@receiver(user_login_failed)
def audit_login_failed(sender, credentials, request=None, **kwargs):
    attempted = (credentials or {}).get("username", "")
    record(
        AuditAction.LOGIN_FAILED,
        request=request,
        summary=f"Failed sign-in attempt for “{attempted[:60]}”",
        details={"username": attempted[:60]},
    )
