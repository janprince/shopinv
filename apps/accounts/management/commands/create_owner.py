"""Create the first owner account so someone can sign in."""

from __future__ import annotations

import getpass
import os
import sys

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role
from apps.core.models import ShopSettings

User = get_user_model()


class Command(BaseCommand):
    help = "Create (or promote) an owner account for the shop."

    def add_arguments(self, parser):
        parser.add_argument("--username")
        parser.add_argument("--email", default="")
        parser.add_argument("--first-name", default="")
        parser.add_argument("--last-name", default="")
        parser.add_argument(
            "--password", help="Avoid on a shared machine; you will be prompted instead."
        )
        parser.add_argument(
            "--from-env",
            action="store_true",
            help="Read OWNER_USERNAME, OWNER_EMAIL and OWNER_PASSWORD from the environment.",
        )
        parser.add_argument(
            "--skip-if-exists",
            action="store_true",
            help="Do nothing if any owner already exists. Useful in deployment scripts.",
        )

    def handle(self, *args, **options):
        if options["skip_if_exists"] and User.objects.filter(role=Role.OWNER).exists():
            self.stdout.write(self.style.WARNING("An owner already exists — nothing to do."))
            return

        if options["from_env"]:
            username = os.environ.get("OWNER_USERNAME", "")
            email = os.environ.get("OWNER_EMAIL", "")
            password = os.environ.get("OWNER_PASSWORD", "")
            if not username or not password:
                # --skip-if-exists marks this as a deploy hook. Failing the whole
                # deployment because the operator has not set the variables yet
                # would be worse than saying so and carrying on.
                if options["skip_if_exists"]:
                    self.stdout.write(
                        self.style.WARNING(
                            "No owner exists yet and OWNER_USERNAME / OWNER_PASSWORD are "
                            "not set, so none was created. Set them and redeploy, or run "
                            "`python manage.py create_owner` against this environment."
                        )
                    )
                    return
                raise CommandError("OWNER_USERNAME and OWNER_PASSWORD must both be set.")
        else:
            username = options["username"] or self._ask("Username")
            email = options["email"] or self._ask("Email address (optional)", required=False)
            password = options["password"] or self._ask_password()

        username = username.strip()
        if not username:
            raise CommandError("A username is required.")

        existing = User.objects.filter(username__iexact=username).first()

        try:
            password_validation.validate_password(password)
        except ValidationError as exc:
            raise CommandError("Password rejected: " + "; ".join(exc.messages)) from exc

        with transaction.atomic():
            if existing:
                existing.role = Role.OWNER
                existing.is_active = True
                existing.set_password(password)
                if email:
                    existing.email = email
                existing.save()
                user = existing
                action = "updated and promoted to owner"
            else:
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=options.get("first_name", "") or "",
                    last_name=options.get("last_name", "") or "",
                    role=Role.OWNER,
                    is_staff=True,
                )
                action = "created"
            ShopSettings.load()

        self.stdout.write(self.style.SUCCESS(f"Owner “{user.username}” {action}."))
        self.stdout.write("Sign in at /accounts/login/")

    def _ask(self, label: str, required: bool = True) -> str:
        if not sys.stdin.isatty():
            raise CommandError(f"{label} is required. Pass it as an option or use --from-env.")
        while True:
            value = input(f"{label}: ").strip()
            if value or not required:
                return value
            self.stderr.write("This cannot be empty.")

    def _ask_password(self) -> str:
        if not sys.stdin.isatty():
            raise CommandError("A password is required. Pass --password or use --from-env.")
        while True:
            first = getpass.getpass("Password: ")
            second = getpass.getpass("Password again: ")
            if first != second:
                self.stderr.write("The two passwords do not match. Try again.")
                continue
            if len(first) < 8:
                self.stderr.write("Use at least 8 characters.")
                continue
            return first
