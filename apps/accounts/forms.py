from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower

User = get_user_model()


class ShopLoginForm(AuthenticationForm):
    """Login with either a username or an email address."""

    username = forms.CharField(
        label="Username or email",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "username",
                "autocapitalize": "none",
                "autocorrect": "off",
                "placeholder": "e.g. ama",
                "data-autofocus": "always",
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
                "id": "id_password",
            }
        ),
    )

    error_messages = {
        "invalid_login": "That username or password is not correct. Please try again.",
        "inactive": "This account has been switched off. Ask the shop owner to switch it back on.",
    }


class UserForm(forms.ModelForm):
    """Owner-only. Creating or editing a member of staff."""

    password1 = forms.CharField(
        label="Password",
        strip=False,
        required=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
        help_text="At least 8 characters. Leave blank to keep the current password.",
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        required=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "username", "email", "phone", "role", "is_active"]
        labels = {
            "first_name": "First name",
            "last_name": "Last name",
            "username": "Username",
            "email": "Email address",
            "phone": "Phone number",
            "role": "Role",
            "is_active": "Account is switched on",
        }
        help_texts = {
            "username": "What they type to sign in. Short and lowercase works best.",
            "email": "Optional. They can sign in with this instead of the username.",
            "is_active": "Switch off to stop someone signing in without losing their history.",
        }
        widgets = {
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "autocomplete": "given-name"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "form-control", "autocomplete": "family-name"}
            ),
            "username": forms.TextInput(
                attrs={"class": "form-control", "autocapitalize": "none", "autocomplete": "off"}
            ),
            "email": forms.EmailInput(attrs={"class": "form-control", "autocomplete": "off"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "inputmode": "tel"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, editing_self: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.editing_self = editing_self
        self.fields["first_name"].required = True
        if self.instance.pk is None:
            self.fields["password1"].required = True
            self.fields["password2"].required = True
            self.fields["password1"].help_text = "At least 8 characters."
        if editing_self:
            # Owners must not be able to lock themselves out of their own shop.
            self.fields["role"].disabled = True
            self.fields["is_active"].disabled = True
            self.fields["role"].help_text = "You cannot change your own role."
            self.fields["is_active"].help_text = "You cannot switch off your own account."

    def clean_username(self):
        username = (self.cleaned_data["username"] or "").strip()
        clash = User.objects.annotate(u=Lower("username")).filter(u=username.lower())
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError("Someone already uses that username. Pick another one.")
        return username

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            return ""
        clash = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError("Someone already uses that email address.")
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "The two passwords do not match.")
            else:
                try:
                    password_validation.validate_password(p1, self.instance)
                except ValidationError as exc:
                    self.add_error("password1", exc)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password1")
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user


class ProfileForm(forms.ModelForm):
    """What any signed-in user may change about themselves."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone"]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "inputmode": "tel"}),
        }

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Someone already uses that email address.")
        return email


class ChangeOwnPasswordForm(forms.Form):
    current_password = forms.CharField(
        label="Current password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "autocomplete": "current-password"}
        ),
    )
    new_password1 = forms.CharField(
        label="New password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "new-password",
                "id": "id_new_password1",
            }
        ),
        help_text="At least 8 characters, and not something easy to guess.",
    )
    new_password2 = forms.CharField(
        label="Confirm new password",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        value = self.cleaned_data["current_password"]
        if not self.user.check_password(value):
            raise ValidationError("That is not your current password.")
        return value

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("new_password1"), cleaned.get("new_password2")
        if p1 and p2 and p1 != p2:
            self.add_error("new_password2", "The two passwords do not match.")
        elif p1:
            try:
                password_validation.validate_password(p1, self.user)
            except ValidationError as exc:
                self.add_error("new_password1", exc)
        return cleaned

    def save(self):
        self.user.set_password(self.cleaned_data["new_password1"])
        self.user.save(update_fields=["password"])
        return self.user


class OwnerResetPasswordForm(SetPasswordForm):
    """Owner sets a new password for someone who has forgotten theirs."""

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control", "autocomplete": "new-password"})
        self.fields["new_password1"].label = "New password"
        self.fields["new_password2"].label = "Confirm new password"
        self.fields[
            "new_password1"
        ].help_text = (
            "Tell them this password in person and ask them to change it after signing in."
        )
