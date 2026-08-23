from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.core.audit import AuditAction, changed_fields, record, snapshot
from apps.core.permissions import owner_required

from .forms import (
    ChangeOwnPasswordForm,
    OwnerResetPasswordForm,
    ProfileForm,
    ShopLoginForm,
    UserForm,
)
from .models import Role

User = get_user_model()


class ShopLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = ShopLoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["has_any_user"] = User.objects.exists()
        return context


class ShopLogoutView(LogoutView):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            record(
                AuditAction.LOGOUT,
                actor=request.user,
                request=request,
                summary=f"{request.user.display_name} signed out",
            )
        return super().dispatch(request, *args, **kwargs)


# --------------------------------------------------------------------------------------
# Profile — available to everyone for their own account
# --------------------------------------------------------------------------------------
@login_required
def profile(request):
    tracked = ["first_name", "last_name", "email", "phone"]
    before = snapshot(request.user, tracked)
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        diff = changed_fields(before, snapshot(user, tracked))
        if diff:
            record(
                AuditAction.USER_UPDATED,
                request=request,
                obj=user,
                summary=f"{user.display_name} updated their own details",
                details={"changes": diff},
            )
        messages.success(request, "Your details have been saved.")
        return redirect("accounts:profile")

    return render(
        request,
        "accounts/profile.html",
        {"form": form, "password_form": ChangeOwnPasswordForm(request.user)},
    )


@login_required
@require_http_methods(["POST"])
def change_password(request):
    form = ChangeOwnPasswordForm(request.user, request.POST)
    if form.is_valid():
        form.save()
        update_session_auth_hash(request, request.user)
        record(
            AuditAction.PASSWORD_RESET,
            request=request,
            obj=request.user,
            summary=f"{request.user.display_name} changed their own password",
        )
        messages.success(request, "Your password has been changed.")
        return redirect("accounts:profile")

    return render(
        request,
        "accounts/profile.html",
        {"form": ProfileForm(instance=request.user), "password_form": form},
    )


# --------------------------------------------------------------------------------------
# User management — owner only
# --------------------------------------------------------------------------------------
@owner_required
def user_list(request):
    users = User.objects.annotate(
        sale_count=Count("sales", filter=Q(sales__status="completed"), distinct=True),
        last_sale=Max("sales__completed_at"),
    ).order_by("-is_active", "first_name", "username")
    return render(
        request,
        "accounts/user_list.html",
        {
            "users": users,
            "owner_count": User.objects.filter(role=Role.OWNER, is_active=True).count(),
        },
    )


@owner_required
def user_create(request):
    form = UserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        record(
            AuditAction.USER_CREATED,
            request=request,
            obj=user,
            summary=f"Created {user.get_role_display().lower()} account for {user.display_name}",
            details={"username": user.username, "role": user.role},
        )
        messages.success(
            request,
            f"{user.display_name} can now sign in with the username “{user.username}”.",
        )
        return redirect("accounts:user_list")

    return render(
        request,
        "accounts/user_form.html",
        {"form": form, "is_create": True, "heading": "Add a team member"},
    )


@owner_required
def user_edit(request, pk: int):
    user = get_object_or_404(User, pk=pk)
    editing_self = user.pk == request.user.pk
    tracked = ["first_name", "last_name", "username", "email", "phone", "role", "is_active"]
    before = snapshot(user, tracked)
    form = UserForm(request.POST or None, instance=user, editing_self=editing_self)

    if request.method == "POST" and form.is_valid():
        saved = form.save()
        diff = changed_fields(before, snapshot(saved, tracked))
        if diff:
            record(
                AuditAction.USER_UPDATED,
                request=request,
                obj=saved,
                summary=f"Updated the account for {saved.display_name}",
                details={"changes": diff},
            )
        if form.cleaned_data.get("password1"):
            record(
                AuditAction.PASSWORD_RESET,
                request=request,
                obj=saved,
                summary=f"Password reset for {saved.display_name}",
            )
        messages.success(request, f"{saved.display_name}'s account has been updated.")
        return redirect("accounts:user_list")

    return render(
        request,
        "accounts/user_form.html",
        {
            "form": form,
            "object": user,
            "is_create": False,
            "editing_self": editing_self,
            "heading": f"Edit {user.display_name}",
        },
    )


@owner_required
@require_http_methods(["POST"])
def user_toggle_active(request, pk: int):
    user = get_object_or_404(User, pk=pk)

    if user.pk == request.user.pk:
        messages.error(request, "You cannot switch off your own account.")
        return redirect("accounts:user_list")

    if user.is_active and user.role == Role.OWNER:
        remaining = User.objects.filter(role=Role.OWNER, is_active=True).exclude(pk=user.pk).count()
        if remaining == 0:
            messages.error(
                request,
                "There must always be at least one active owner. Make someone else an owner first.",
            )
            return redirect("accounts:user_list")

    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    state = "switched on" if user.is_active else "switched off"
    record(
        AuditAction.USER_STATUS_CHANGED,
        request=request,
        obj=user,
        summary=f"Account for {user.display_name} was {state}",
        details={"is_active": user.is_active},
    )
    messages.success(request, f"{user.display_name}'s account has been {state}.")
    return redirect("accounts:user_list")


@owner_required
def user_reset_password(request, pk: int):
    user = get_object_or_404(User, pk=pk)
    form = OwnerResetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        record(
            AuditAction.PASSWORD_RESET,
            request=request,
            obj=user,
            summary=f"Owner reset the password for {user.display_name}",
        )
        messages.success(
            request, f"A new password has been set for {user.display_name}. Tell them in person."
        )
        return redirect("accounts:user_list")

    return render(request, "accounts/user_password.html", {"form": form, "object": user})
