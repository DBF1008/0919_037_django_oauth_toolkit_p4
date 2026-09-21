from django.core.management.base import BaseCommand, CommandError

from ...models import clear_expired
from ...settings import oauth2_settings


class Command(BaseCommand):
    help = "Can be run as a cronjob or directly to clean out expired tokens"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=None,
            help=(
                "Number of tokens deleted per batch. "
                "Defaults to the CLEAR_EXPIRED_TOKENS_BATCH_SIZE setting "
                f"({oauth2_settings.CLEAR_EXPIRED_TOKENS_BATCH_SIZE})."
            ),
        )
        parser.add_argument(
            "--batch-interval",
            type=float,
            default=None,
            help=(
                "Seconds to sleep between batch deletions. "
                "Defaults to the CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL setting "
                f"({oauth2_settings.CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL})."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview the tokens that would be deleted without deleting anything.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        batch_interval = options["batch_interval"]
        dry_run = options["dry_run"]

        if batch_size is not None and batch_size < 1:
            raise CommandError("--batch-size must be a positive integer")
        if batch_interval is not None and batch_interval < 0:
            raise CommandError("--batch-interval must be greater than or equal to 0")

        if dry_run:
            self.stdout.write("Dry run: no tokens will be deleted.")

        def report_progress(*, token_type, batch_number, batch_count, deleted_total, remaining, batch_ids):
            self.stdout.write(
                f"[{token_type}] batch {batch_number}: "
                f"{batch_count} tokens, {deleted_total} total, {remaining} remaining"
            )
            if dry_run:
                self.stdout.write(f"[{token_type}] batch {batch_number} ids: {batch_ids}")

        summary = clear_expired(
            batch_size=batch_size,
            batch_interval=batch_interval,
            dry_run=dry_run,
            progress_callback=report_progress,
        )

        for token_type, deleted in summary.items():
            self.stdout.write(f"{token_type}: {deleted} tokens {'found' if dry_run else 'deleted'}")
        total = sum(summary.values())
        if dry_run:
            self.stdout.write(self.style.WARNING(f"{total} expired tokens would be deleted"))
        else:
            self.stdout.write(self.style.SUCCESS(f"{total} expired tokens deleted"))
