from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.core.models import AuditAction, AuditEvent
from apps.core.tests.factories import DEFAULT_PASSWORD, make_owner, make_user

User = get_user_model()


class LoginTests(TestCase):
    def setUp(self):
        self.user = make_user(username="kofi", email="kofi@example.com")

    def test_login_with_username(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "kofi", "password": DEFAULT_PASSWORD},
        )
        self.assertRedirects(response, reverse("core:dashboard"))

    def test_login_with_email_instead_of_username(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "KOFI@example.com", "password": DEFAULT_PASSWORD},
        )
        self.assertRedirects(response, reverse("core:dashboard"))

    def test_login_is_case_insensitive_on_username(self):
        response = self.client.post(
            reverse("accounts:login"), {"username": "KoFi", "password": DEFAULT_PASSWORD}
        )
        self.assertRedirects(response, reverse("core:dashboard"))

    def test_wrong_password_is_rejected_with_a_plain_message(self):
        response = self.client.post(
            reverse("accounts:login"), {"username": "kofi", "password": "nope"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not correct")
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_switched_off_account_cannot_sign_in(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(
            reverse("accounts:login"), {"username": "kofi", "password": DEFAULT_PASSWORD}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_successful_login_is_audited(self):
        self.client.post(
            reverse("accounts:login"), {"username": "kofi", "password": DEFAULT_PASSWORD}
        )
        self.assertTrue(
            AuditEvent.objects.filter(action=AuditAction.LOGIN, actor=self.user).exists()
        )

    def test_failed_login_is_audited(self):
        self.client.post(reverse("accounts:login"), {"username": "kofi", "password": "nope"})
        self.assertTrue(AuditEvent.objects.filter(action=AuditAction.LOGIN_FAILED).exists())

    def test_anonymous_visitor_is_sent_to_login(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertIn(reverse("accounts:login"), response["Location"])


class ProfileExperienceTests(TestCase):
    def setUp(self):
        self.user = make_user(username="esi")
        self.client.force_login(self.user)

    def test_password_change_has_a_focused_get_page(self):
        response = self.client.get(reverse("accounts:change_password"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/change_password.html")
        self.assertContains(response, "Change password")
        self.assertContains(response, 'name="current_password"')

    def test_password_change_post_still_updates_the_password(self):
        response = self.client.post(
            reverse("accounts:change_password"),
            {
                "current_password": DEFAULT_PASSWORD,
                "new_password1": "new-shop-pass-2026",
                "new_password2": "new-shop-pass-2026",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("new-shop-pass-2026"))


class RolePermissionTests(TestCase):
    """The rule lives on the server. Hiding a link is not a permission."""

    OWNER_ONLY = [
        ("core:settings", []),
        ("core:audit_log", []),
        ("core:audit_export", []),
        ("accounts:user_list", []),
        ("accounts:user_create", []),
        ("reports:profit", []),
        ("reports:profit_export", []),
    ]

    def setUp(self):
        self.owner = make_owner()
        self.keeper = make_user()

    def test_shopkeeper_is_refused_every_owner_only_page(self):
        self.client.force_login(self.keeper)
        for name, args in self.OWNER_ONLY:
            with self.subTest(view=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 403)

    def test_owner_reaches_every_owner_only_page(self):
        self.client.force_login(self.owner)
        for name, args in self.OWNER_ONLY:
            with self.subTest(view=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 200)

    def test_shopkeeper_can_reach_the_operational_pages(self):
        self.client.force_login(self.keeper)
        for name in [
            "core:dashboard",
            "sales:pos",
            "sales:history",
            "catalog:product_list",
            "catalog:product_create",
            "inventory:receive",
            "inventory:adjust",
            "inventory:movements",
            "reports:index",
            "reports:sales",
        ]:
            with self.subTest(view=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_shopkeeper_cannot_create_a_user_by_posting_directly(self):
        self.client.force_login(self.keeper)
        response = self.client.post(
            reverse("accounts:user_create"),
            {
                "username": "sneaky",
                "first_name": "S",
                "role": Role.OWNER,
                "password1": "long-enough-pass",
                "password2": "long-enough-pass",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="sneaky").exists())


class UserManagementTests(TestCase):
    def setUp(self):
        self.owner = make_owner()
        self.client.force_login(self.owner)

    def test_owner_creates_a_shopkeeper(self):
        response = self.client.post(
            reverse("accounts:user_create"),
            {
                "first_name": "Kofi",
                "last_name": "Mensah",
                "username": "kofi",
                "email": "kofi@example.com",
                "phone": "0244112233",
                "role": Role.SHOPKEEPER,
                "is_active": "on",
                "password1": "shop-pass-2026",
                "password2": "shop-pass-2026",
            },
        )
        self.assertRedirects(response, reverse("accounts:user_list"))
        created = User.objects.get(username="kofi")
        self.assertEqual(created.role, Role.SHOPKEEPER)
        self.assertTrue(created.check_password("shop-pass-2026"))
        self.assertTrue(AuditEvent.objects.filter(action=AuditAction.USER_CREATED).exists())

    def test_duplicate_username_is_rejected(self):
        make_user(username="kofi")
        response = self.client.post(
            reverse("accounts:user_create"),
            {
                "first_name": "Other",
                "username": "KOFI",
                "role": Role.SHOPKEEPER,
                "password1": "shop-pass-2026",
                "password2": "shop-pass-2026",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already uses that username")

    def test_mismatched_passwords_are_rejected(self):
        response = self.client.post(
            reverse("accounts:user_create"),
            {
                "first_name": "Kofi",
                "username": "kofi",
                "role": Role.SHOPKEEPER,
                "password1": "shop-pass-2026",
                "password2": "different-pass",
            },
        )
        self.assertContains(response, "do not match")

    def test_owner_cannot_switch_off_their_own_account(self):
        response = self.client.post(
            reverse("accounts:user_toggle_active", args=[self.owner.pk]), follow=True
        )
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.assertContains(response, "cannot switch off your own account")

    def test_the_shop_can_never_be_left_without_an_active_owner(self):
        """Two guards cover this: no self-toggle, and no removing the last owner.

        Together they make a zero-owner shop unreachable — an owner switching
        another owner off always leaves themselves.
        """
        second_owner = make_owner(username="yaa")
        self.client.force_login(second_owner)

        # Switching off the other owner is allowed: one active owner remains.
        self.client.post(reverse("accounts:user_toggle_active", args=[self.owner.pk]))
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)

        # Switching off themselves is refused, so an owner always survives.
        response = self.client.post(
            reverse("accounts:user_toggle_active", args=[second_owner.pk]), follow=True
        )
        second_owner.refresh_from_db()
        self.assertTrue(second_owner.is_active)
        self.assertContains(response, "cannot switch off your own account")
        self.assertEqual(User.objects.filter(role=Role.OWNER, is_active=True).count(), 1)

    def test_an_owner_cannot_change_their_own_role_or_switch_themselves_off(self):
        response = self.client.post(
            reverse("accounts:user_edit", args=[self.owner.pk]),
            {
                "first_name": "Ama",
                "last_name": "",
                "username": self.owner.username,
                "email": "",
                "phone": "",
                "role": Role.SHOPKEEPER,
                "is_active": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.role, Role.OWNER)
        self.assertTrue(self.owner.is_active)

    def test_switching_off_a_user_is_audited(self):
        keeper = make_user()
        self.client.post(reverse("accounts:user_toggle_active", args=[keeper.pk]))
        keeper.refresh_from_db()
        self.assertFalse(keeper.is_active)
        self.assertTrue(AuditEvent.objects.filter(action=AuditAction.USER_STATUS_CHANGED).exists())

    def test_a_superuser_is_always_an_owner(self):
        admin = User.objects.create_superuser("root", password="root-pass-2026")
        self.assertTrue(admin.is_owner)
