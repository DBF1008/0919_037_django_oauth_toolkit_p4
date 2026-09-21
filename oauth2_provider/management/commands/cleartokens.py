import time

from django.core.management.base import BaseCommand

from ...models import (
    clear_expired,
    get_access_token_model,
    get_grant_model,
    get_id_token_model,
    get_refresh_token_model,
)
from ...settings import oauth2_settings


STAGE_LABELS = {
    "revoked_refresh_tokens": "Revoked refresh tokens",
    "expired_refresh_tokens": "Expired refresh tokens",
    "access_tokens": "Expired access tokens",
    "id_tokens": "Expired ID tokens",
    "grants": "Expired grants",
}

# Human-readable identifier printed for each stage in dry-run mode.
STAGE_IDENTIFIERS = {
    "revoked_refresh_tokens": (get_refresh_token_model, "token"),
    "expired_refresh_tokens": (get_refresh_token_model, "token"),
    "access_tokens": (get_access_token_model, "token"),
    "id_tokens": (get_id_token_model, "jti"),
    "grants": (get_grant_model, "code"),
}


class Command(BaseCommand):
    help = "Can be run as a cronjob or directly to clean out expired tokens"

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--batch-size",
            type=int,
            default=None,
            help=(
                "Number of tokens deleted per batch (defaults to "
                "CLEAR_EXPIRED_TOKENS_BATCH_SIZE from settings)."
            ),
        )
        parser.add_argument(
            "--batch-interval",
            type=float,
            default=None,
            help=(
                "Seconds to pause between batches (defaults to "
                "CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL from settings)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Preview the tokens that would be deleted without removing anything.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        batch_interval = options["batch_interval"]
        dry_run = options["dry_run"]
        verbose = options["verbosity"] > 1

        if batch_size is not None and batch_size <= 0:
            self.stderr.write(self.style.ERROR("--batch-size must be a positive integer."))
            return
        if batch_interval is not None and batch_interval < 0:
            self.stderr.write(self.style.ERROR("--batch-interval cannot be negative."))
            return

        effective_batch_size = (
            batch_size if batch_size is not None else oauth2_settings.CLEAR_EXPIRED_TOKENS_BATCH_SIZE
        )
        effective_batch_interval = (
            batch_interval
            if batch_interval is not None
            else oauth2_settings.CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: no tokens will be deleted."))
        self.stdout.write(f"Batch size: {effective_batch_size}, batch interval: {effective_batch_interval}s")

        stage_batches = {stage: 0 for stage in STAGE_LABELS}
        stage_started = time.monotonic()

        def progress_callback(stage, deleted_in_batch, deleted_total, remaining, batch_ids=None):
            stage_batches[stage] += 1
            label = STAGE_LABELS.get(stage, stage)
            if dry_run and batch_ids:
                model_getter, identifier_field = STAGE_IDENTIFIERS[stage]
                model = model_getter()
                tokens = model.objects.filter(id__in=batch_ids).values_list(identifier_field, flat=True)
                for token in tokens:
                    self.stdout.write(self.style.WARNING(f"[dry-run] {label}: {token}"))
            if not dry_run and (verbose or remaining == 0 or stage_batches[stage] == 1):
                self.stdout.write(
                    f"{label}: deleted {deleted_total} (last batch {deleted_in_batch}, remaining {remaining})"
                )

        result = clear_expired(
            batch_size=batch_size,
            batch_interval=batch_interval,
            dry_run=dry_run,
            progress_callback=progress_callback,
        )

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run summary (nothing was deleted):"))
        else:
            self.stdout.write(self.style.SUCCESS("Clear expired summary:"))
        for stage, label in STAGE_LABELS.items():
            self.stdout.write(f"  {label}: {result.as_dict()[stage]}")
        self.stdout.write(f"Elapsed: {time.monotonic() - stage_started:.3f}s")
