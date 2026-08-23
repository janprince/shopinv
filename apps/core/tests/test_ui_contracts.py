from django.test import TestCase
from django.urls import reverse

from apps.core.tests.factories import make_owner


class SharedUiContractTests(TestCase):
    def setUp(self):
        self.owner = make_owner()
        self.client.force_login(self.owner)

    def test_offline_page_does_not_claim_unsaved_forms_are_persisted(self):
        response = self.client.get(reverse("core:offline"))
        self.assertContains(response, "Forms outside New Sale are not saved on this device")
        self.assertNotContains(response, "Anything you had typed is still on this device")

    def test_shell_title_is_not_a_second_h1(self):
        response = self.client.get(reverse("accounts:user_list"))
        html = response.content.decode()
        self.assertEqual(html.count("<h1"), 1)
        self.assertIn('class="topbar-title"', html)

    def test_reports_render_the_compact_mobile_switcher(self):
        response = self.client.get(reverse("reports:profit"))
        self.assertContains(response, 'id="report-switcher"')
        self.assertContains(response, 'class="filter-disclosure period-disclosure no-print"')
