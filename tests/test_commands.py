from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from oauth2_provider.models import (
    get_access_token_model,
    get_application_model,
    get_grant_model,
    get_refresh_token_model,
)

from . import presets
from .common_testing import OAuth2ProviderTestCase as TestCase


Application = get_application_model()
AccessToken = get_access_token_model()
RefreshToken = get_refresh_token_model()
Grant = get_grant_model()


class CreateApplicationTest(TestCase):
    def test_command_creates_application(self):
        output = StringIO()
        self.assertEqual(Application.objects.count(), 0)
        call_command(
            "createapplication",
            "confidential",
            "authorization-code",
            "--redirect-uris=http://example.com http://example2.com",
            stdout=output,
        )
        self.assertEqual(Application.objects.count(), 1)
        self.assertIn("created successfully", output.getvalue())

    def test_missing_required_args(self):
        self.assertEqual(Application.objects.count(), 0)
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "createapplication",
                "--redirect-uris=http://example.com http://example2.com",
            )

        self.assertIn("client_type", ctx.exception.args[0])
        self.assertIn("authorization_grant_type", ctx.exception.args[0])
        self.assertEqual(Application.objects.count(), 0)

    def test_command_creates_application_with_skipped_auth(self):
        self.assertEqual(Application.objects.count(), 0)
        call_command(
            "createapplication",
            "confidential",
            "authorization-code",
            "--redirect-uris=http://example.com http://example2.com",
            "--skip-authorization",
        )
        app = Application.objects.get()

        self.assertTrue(app.skip_authorization)

    def test_application_created_normally_with_no_skipped_auth(self):
        call_command(
            "createapplication",
            "confidential",
            "authorization-code",
            "--redirect-uris=http://example.com http://example2.com",
        )
        app = Application.objects.get()

        self.assertFalse(app.skip_authorization)

    def test_application_created_with_name(self):
        call_command(
            "createapplication",
            "confidential",
            "authorization-code",
            "--redirect-uris=http://example.com http://example2.com",
            "--name=TEST",
        )
        app = Application.objects.get()

        self.assertEqual(app.name, "TEST")

    def test_application_created_with_client_secret(self):
        call_command(
            "createapplication",
            "confidential",
            "authorization-code",
            "--redirect-uris=http://example.com http://example2.com",
            "--client-secret=SECRET",
        )
        app = Application.objects.get()

        self.assertTrue(check_password("SECRET", app.client_secret))

    def test_application_created_with_client_id(self):
        call_command(
            "createapplication",
            "confidential",
            "authorization-code",
            "--redirect-uris=http://example.com http://example2.com",
            "--client-id=someId",
        )
        app = Application.objects.get()

        self.assertEqual(app.client_id, "someId")

    def test_application_created_with_user(self):
        User = get_user_model()
        user = User.objects.create()
        call_command(
            "createapplication",
            "confidential",
            "authorization-code",
            "--redirect-uris=http://example.com http://example2.com",
            "--user=%s" % user.pk,
        )
        app = Application.objects.get()

        self.assertEqual(app.user, user)

    @pytest.mark.usefixtures("oauth2_settings")
    @pytest.mark.oauth2_settings(presets.OIDC_SETTINGS_RW)
    def test_application_created_with_algorithm(self):
        call_command(
            "createapplication",
            "confidential",
            "authorization-code",
            "--redirect-uris=http://example.com http://example2.com",
            "--algorithm=RS256",
        )
        app = Application.objects.get()

        self.assertEqual(app.algorithm, "RS256")

    def test_validation_failed_message(self):
        import django

        output = StringIO()
        call_command(
            "createapplication",
            "confidential",
            "authorization-code",
            "--redirect-uris=http://example.com http://example2.com",
            "--user=783",
            stdout=output,
        )

        output_str = output.getvalue()
        self.assertIn("user", output_str)
        self.assertIn("783", output_str)
        if django.VERSION < (5, 2):
            self.assertIn("does not exist", output_str)
        else:
            self.assertIn("is not a valid choice", output_str)


@pytest.mark.usefixtures("oauth2_settings")
class ClearTokensTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("test_user", "test@example.com", "123456")
        cls.application = Application.objects.create(
            name="test_app",
            user=cls.user,
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        )
        now = timezone.now()
        cls.expired_access_token = AccessToken.objects.create(
            token="expired access token",
            expires=now - timedelta(days=2),
        )
        cls.current_access_token = AccessToken.objects.create(
            token="current access token",
            expires=now + timedelta(days=1),
        )
        cls.expired_refresh_token = RefreshToken.objects.create(
            token="expired refresh token",
            application=cls.application,
            access_token=cls.expired_access_token,
            user=cls.user,
        )
        cls.expired_grant = Grant.objects.create(
            user=cls.user,
            code="expired grant",
            application=cls.application,
            expires=now - timedelta(days=1),
            redirect_uri="https://localhost/redirect",
        )
        cls.current_grant = Grant.objects.create(
            user=cls.user,
            code="current grant",
            application=cls.application,
            expires=now + timedelta(days=1),
            redirect_uri="https://localhost/redirect",
        )

    def setUp(self):
        self.oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 3600

    def test_command_deletes_expired_tokens_with_progress_output(self):
        output = StringIO()
        call_command("cleartokens", "--batch-size=1", "--batch-interval=0", stdout=output)

        # expired tokens are gone, current ones are kept
        self.assertFalse(AccessToken.objects.filter(pk=self.expired_access_token.pk).exists())
        self.assertTrue(AccessToken.objects.filter(pk=self.current_access_token.pk).exists())
        self.assertEqual(RefreshToken.objects.count(), 0)
        self.assertFalse(Grant.objects.filter(pk=self.expired_grant.pk).exists())
        self.assertTrue(Grant.objects.filter(pk=self.current_grant.pk).exists())

        output_str = output.getvalue()
        self.assertIn("[access_token] batch 1", output_str)
        self.assertIn("remaining", output_str)
        self.assertIn("expired tokens deleted", output_str)

    def test_command_dry_run_only_previews_tokens(self):
        output = StringIO()
        call_command("cleartokens", "--dry-run", stdout=output)

        # nothing was deleted
        self.assertEqual(AccessToken.objects.count(), 2)
        self.assertEqual(RefreshToken.objects.count(), 1)
        self.assertEqual(Grant.objects.count(), 2)

        output_str = output.getvalue()
        self.assertIn("Dry run", output_str)
        self.assertIn("ids:", output_str)
        self.assertIn(str(self.expired_access_token.pk), output_str)
        self.assertIn("would be deleted", output_str)

    def test_command_rejects_invalid_batch_size(self):
        with self.assertRaises(CommandError):
            call_command("cleartokens", "--batch-size=0")

    def test_command_rejects_invalid_batch_interval(self):
        with self.assertRaises(CommandError):
            call_command("cleartokens", "--batch-interval=-1")
