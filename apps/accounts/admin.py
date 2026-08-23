from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ["username", "display_name", "role", "is_active", "last_login"]
    list_filter = ["role", "is_active", "is_superuser"]
    fieldsets = (*DjangoUserAdmin.fieldsets, ("Shop", {"fields": ("role", "phone")}))
    add_fieldsets = (
        *DjangoUserAdmin.add_fieldsets,
        ("Shop", {"fields": ("role", "phone", "first_name", "last_name", "email")}),
    )
