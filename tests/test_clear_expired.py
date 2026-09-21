from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from oauth2_provider.metrics import PROMETHEUS_ENABLED
from oauth2_provider.models import (
    ClearExpiredResult,
    clear_expired,
    get_access_token_model,
    get_application_model,
    get_grant_model,
    get_id_token_model,
    get_refresh_token_model,
)


Application = get_application_model()
AccessToken = get_access_token_model()
RefreshToken = get_refresh_token_model()
Grant = get_grant_model()
IDToken = get_id_token_model()


pytestmark = pytest.mark.usefixtures("oauth2_settings")


@pytest.fixture
def token_scenario(db, django_user_model):
    user = django_user_model.objects.create_user("clear_user", "clear@example.com", "secret")
    application = Application.objects.create(
        name="clear_app",
        redirect_uris="http://localhost http://example.com",
        user=user,
        client_type=Application.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
    )
    now = timezone.now()
    expired_at = now - timedelta(seconds=500)
    valid_at = now + timedelta(seconds=500)

    expired_linked_access = AccessToken.objects.create(
        token="expired-linked-access", expires=expired_at, application=application, user=user
    )
    expired_orphan_access = AccessToken.objects.create(
        token="expired-orphan-access", expires=expired_at, application=application, user=user
    )
    valid_access = AccessToken.objects.create(
        token="valid-access", expires=valid_at, application=application, user=user
    )
    linked_refresh = RefreshToken.objects.create(
        token="linked-refresh",
        application=application,
        user=user,
        access_token=expired_linked_access,
    )
    valid_refresh = RefreshToken.objects.create(
        token="valid-refresh",
        application=application,
        user=user,
        access_token=valid_access,
    )
    revoked_refresh = RefreshToken.objects.create(
        token="revoked-refresh",
        application=application,
        user=user,
        revoked=expired_at,
    )
    expired_grant = Grant.objects.create(
        user=user,
        code="expired-grant",
        application=application,
        expires=expired_at,
        redirect_uri="http://localhost",
    )
    valid_grant = Grant.objects.create(
        user=user,
        code="valid-grant",
        application=application,
        expires=valid_at,
        redirect_uri="http://localhost",
    )
    return {
        "user": user,
        "application": application,
        "expired_linked_access": expired_linked_access,
        "expired_orphan_access": expired_orphan_access,
        "valid_access": valid_access,
        "linked_refresh": linked_refresh,
        "valid_refresh": valid_refresh,
        "revoked_refresh": revoked_refresh,
        "expired_grant": expired_grant,
        "valid_grant": valid_grant,
    }


@pytest.mark.parametrize("kwargs", [{"batch_size": 0}, {"batch_size": -1}, {"batch_interval": -1}])
def test_clear_expired_rejects_invalid_batch_options(oauth2_settings, token_scenario, kwargs):
    with pytest.raises(ValueError):
        clear_expired(**kwargs)


def test_clear_expired_returns_result_object(oauth2_settings, token_scenario):
    oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
    result = clear_expired()
    assert isinstance(result, ClearExpiredResult)
    assert result.access_tokens >= 2
    assert result.expired_refresh_tokens == 1
    assert result.revoked_refresh_tokens == 1
    assert result.grants == 1
    assert not RefreshToken.objects.filter(token="linked-refresh").exists()
    assert not RefreshToken.objects.filter(token="revoked-refresh").exists()
    assert not AccessToken.objects.filter(token="expired-linked-access").exists()
    assert not AccessToken.objects.filter(token="expired-orphan-access").exists()
    assert not Grant.objects.filter(code="expired-grant").exists()


def test_clear_expired_preserves_valid_tokens(oauth2_settings, token_scenario):
    oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
    clear_expired()
    assert AccessToken.objects.filter(token="valid-access").exists()
    assert RefreshToken.objects.filter(token="valid-refresh").exists()
    assert Grant.objects.filter(code="valid-grant").exists()


def test_clear_expired_explicit_batch_arguments(oauth2_settings, token_scenario):
    oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
    calls = []

    def callback(stage, in_batch, total, remaining, batch_ids):
        calls.append((stage, in_batch, total, remaining))

    result = clear_expired(batch_size=1, batch_interval=0, progress_callback=callback)
    assert result.expired_refresh_tokens == 1
    stages = [call[0] for call in calls]
    assert "access_tokens" in stages
    assert "expired_refresh_tokens" in stages
    assert "grants" in stages
    for call in calls:
        assert call[1] == 1


def test_clear_expired_batch_interval_sleeps(oauth2_settings, token_scenario, mocker):
    oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
    sleep_mock = mocker.patch("oauth2_provider.models.time.sleep")
    clear_expired(batch_size=1, batch_interval=0.25)
    assert sleep_mock.called
    assert all(call.args[0] == 0.25 for call in sleep_mock.call_args_list)


def test_clear_expired_dry_run_deletes_nothing(oauth2_settings, token_scenario):
    oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
    access_before = AccessToken.objects.count()
    refresh_before = RefreshToken.objects.count()
    grant_before = Grant.objects.count()

    result = clear_expired(batch_size=2, dry_run=True)

    assert AccessToken.objects.count() == access_before
    assert RefreshToken.objects.count() == refresh_before
    assert Grant.objects.count() == grant_before
    assert result.access_tokens >= 2
    assert result.expired_refresh_tokens == 1
    assert result.revoked_refresh_tokens == 1
    assert result.grants == 1


def test_clear_expired_dry_run_reports_batch_ids(oauth2_settings, token_scenario):
    oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
    seen = {"access_tokens": [], "expired_refresh_tokens": [], "grants": []}

    def callback(stage, in_batch, total, remaining, batch_ids):
        if stage in seen and batch_ids:
            seen[stage].extend(batch_ids)

    clear_expired(batch_size=1, dry_run=True, progress_callback=callback)

    assert set(seen["expired_refresh_tokens"]) == {token_scenario["linked_refresh"].pk}
    assert token_scenario["expired_linked_access"].pk in set(seen["access_tokens"])
    assert token_scenario["expired_orphan_access"].pk in set(seen["access_tokens"])
    assert set(seen["grants"]) == {token_scenario["expired_grant"].pk}


def test_clear_expired_refresh_token_deletion_order(oauth2_settings, token_scenario):
    """Within a batch, linked access tokens are deleted before refresh tokens."""
    oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
    linked_access_pk = token_scenario["expired_linked_access"].pk
    linked_refresh_pk = token_scenario["linked_refresh"].pk
    events = []

    def callback(stage, in_batch, total, remaining, batch_ids):
        if stage == "access_tokens" and in_batch and linked_access_pk:
            # The callback fires right after the access token deletion and
            # before the refresh token is removed within the same batch.
            access_gone = not AccessToken.objects.filter(pk=linked_access_pk).exists()
            refresh_still_there = RefreshToken.objects.filter(pk=linked_refresh_pk).exists()
            if access_gone and refresh_still_there:
                events.append("access_before_refresh")
        if stage == "expired_refresh_tokens" and batch_ids and linked_refresh_pk in batch_ids:
            if not AccessToken.objects.filter(pk=linked_access_pk).exists():
                events.append("refresh_after_access")

    clear_expired(batch_size=1, progress_callback=callback)
    assert "access_before_refresh" in events
    assert "refresh_after_access" in events
    assert not RefreshToken.objects.filter(pk=linked_refresh_pk).exists()


def test_clear_expired_linked_id_token_cascade(oauth2_settings, token_scenario):
    oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
    id_token = IDToken.objects.create(
        user=token_scenario["user"],
        application=token_scenario["application"],
        expires=token_scenario["expired_linked_access"].expires,
        scope="",
    )
    token_scenario["expired_linked_access"].id_token = id_token
    token_scenario["expired_linked_access"].save()

    clear_expired(batch_size=1)
    assert not IDToken.objects.filter(pk=id_token.pk).exists()


@pytest.mark.skipif(not PROMETHEUS_ENABLED, reason="prometheus_client not installed")
def test_clear_expired_records_prometheus_metrics(oauth2_settings, token_scenario):
    from prometheus_client import REGISTRY

    oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
    duration_before = (
        REGISTRY.get_sample_value(
            "oauth2_provider_clear_expired_duration_seconds_count",
            {"status": "success"},
        )
        or 0
    )
    deleted_before = (
        REGISTRY.get_sample_value(
            "oauth2_provider_clear_expired_deleted_total",
            {"token_type": "expired_refresh_tokens"},
        )
        or 0
    )

    clear_expired(batch_size=1)

    deleted = REGISTRY.get_sample_value(
        "oauth2_provider_clear_expired_deleted_total",
        {"token_type": "expired_refresh_tokens"},
    )
    assert deleted - deleted_before == 1
    duration_count = REGISTRY.get_sample_value(
        "oauth2_provider_clear_expired_duration_seconds_count",
        {"status": "success"},
    )
    assert duration_count - duration_before == 1
    remaining_grants = REGISTRY.get_sample_value(
        "oauth2_provider_clear_expired_remaining",
        {"token_type": "grants"},
    )
    assert remaining_grants == 0


@pytest.mark.skipif(not PROMETHEUS_ENABLED, reason="prometheus_client not installed")
def test_clear_expired_records_failure_metric(oauth2_settings, token_scenario, mocker):
    from prometheus_client import REGISTRY

    oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
    failure_before = (
        REGISTRY.get_sample_value(
            "oauth2_provider_clear_expired_duration_seconds_count",
            {"status": "failure"},
        )
        or 0
    )
    mocker.patch("oauth2_provider.models.time.sleep", side_effect=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        clear_expired(batch_size=1, batch_interval=0.1)
    duration_count = REGISTRY.get_sample_value(
        "oauth2_provider_clear_expired_duration_seconds_count",
        {"status": "failure"},
    )
    assert duration_count - failure_before == 1


@pytest.mark.skipif(not PROMETHEUS_ENABLED, reason="prometheus_client not installed")
def test_clear_expired_dry_run_does_not_increment_deleted_metric(oauth2_settings, token_scenario):
    from prometheus_client import REGISTRY

    oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
    before = REGISTRY.get_sample_value(
        "oauth2_provider_clear_expired_deleted_total",
        {"token_type": "grants"},
    )
    clear_expired(dry_run=True)
    after = REGISTRY.get_sample_value(
        "oauth2_provider_clear_expired_deleted_total",
        {"token_type": "grants"},
    )
    assert (after or 0) == (before or 0)


class TestClearTokensCommand:
    def test_command_clears_tokens(self, oauth2_settings, token_scenario):
        oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
        out = StringIO()
        call_command("cleartokens", stdout=out)
        output = out.getvalue()
        assert "Clear expired summary" in output
        assert not RefreshToken.objects.filter(token="linked-refresh").exists()
        assert not Grant.objects.filter(code="expired-grant").exists()

    def test_command_dry_run_previews_tokens(self, oauth2_settings, token_scenario):
        oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
        out = StringIO()
        call_command("cleartokens", "--dry-run", stdout=out)
        output = out.getvalue()
        assert "Dry run" in output
        assert "linked-refresh" in output
        assert "expired-grant" in output
        assert RefreshToken.objects.filter(token="linked-refresh").exists()
        assert Grant.objects.filter(code="expired-grant").exists()

    def test_command_batch_size_and_interval_arguments(self, oauth2_settings, token_scenario, mocker):
        oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
        sleep_mock = mocker.patch("oauth2_provider.models.time.sleep")
        out = StringIO()
        call_command(
            "cleartokens",
            "--batch-size=1",
            "--batch-interval=0.1",
            stdout=out,
        )
        assert sleep_mock.called
        assert "Batch size: 1, batch interval: 0.1s" in out.getvalue()

    def test_command_invalid_batch_size(self, oauth2_settings, token_scenario):
        out = StringIO()
        call_command("cleartokens", "--batch-size=0", stderr=out)
        assert "positive integer" in out.getvalue()

    def test_command_negative_batch_interval(self, oauth2_settings, token_scenario):
        out = StringIO()
        call_command("cleartokens", "--batch-interval=-0.1", stderr=out)
        assert "cannot be negative" in out.getvalue()

    def test_command_uses_settings_defaults(self, oauth2_settings, token_scenario):
        oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
        oauth2_settings.CLEAR_EXPIRED_TOKENS_BATCH_SIZE = 7
        oauth2_settings.CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL = 0.0
        out = StringIO()
        call_command("cleartokens", stdout=out)
        assert "Batch size: 7, batch interval: 0.0s" in out.getvalue()

    def test_command_progress_output(self, oauth2_settings, token_scenario):
        oauth2_settings.REFRESH_TOKEN_EXPIRE_SECONDS = 100
        out = StringIO()
        call_command("cleartokens", "--batch-size=1", "-v", "2", stdout=out)
        output = out.getvalue()
        assert "deleted" in output
        assert "remaining 0" in output
