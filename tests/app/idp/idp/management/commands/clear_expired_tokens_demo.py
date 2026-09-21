"""Demo command showing programmatic use of clear_expired from the IDP app."""

from django.core.management.base import BaseCommand

from oauth2_provider.models import clear_expired


class Command(BaseCommand):
    help = "Demo: clear expired OAuth tokens with batching, progress and optional dry-run"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=None)
        parser.add_argument("--batch-interval", type=float, default=None)
        parser.add_argument("--dry-run", action="store_true", default=False)

    def handle(self, *args, **options):
        result = clear_expired(
            batch_size=options["batch_size"],
            batch_interval=options["batch_interval"],
            dry_run=options["dry_run"],
            progress_callback=lambda stage, in_batch, total, remaining, ids: self.stdout.write(
                f"{stage}: batch={in_batch} total={total} remaining={remaining}"
            ),
        )
        prefix = "[dry-run] would delete" if options["dry_run"] else "deleted"
        for token_type, count in result.as_dict().items():
            self.stdout.write(f"{prefix} {count} {token_type}")
