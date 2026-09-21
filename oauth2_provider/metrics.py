"""
Prometheus metrics for django-oauth-toolkit.

Metrics are exposed through the `prometheus_client` library when it is
installed (e.g. via the ``metrics`` extra) and silently become no-ops
otherwise, so monitoring is strictly opt-in and never a hard dependency.
"""

import logging


logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Gauge, Histogram

    PROMETHEUS_ENABLED = True
except ImportError:  # pragma: no cover - exercised only without prometheus_client
    PROMETHEUS_ENABLED = False

    class _NoopMetric:
        """Fallback used when ``prometheus_client`` is not installed."""

        def labels(self, *args, **kwargs):
            return self

        def inc(self, *args, **kwargs):
            return None

        def observe(self, *args, **kwargs):
            return None

        def set(self, *args, **kwargs):
            return None

    def _noop_metric(*args, **kwargs):
        return _NoopMetric()

    Counter = Gauge = Histogram = _noop_metric


clear_expired_duration = Histogram(
    "oauth2_provider_clear_expired_duration_seconds",
    "Time spent running clear_expired to remove expired tokens.",
    ["status"],
)

clear_expired_deleted_total = Counter(
    "oauth2_provider_clear_expired_deleted_total",
    "Number of expired records deleted by clear_expired.",
    ["token_type"],
)

clear_expired_remaining = Gauge(
    "oauth2_provider_clear_expired_remaining",
    "Number of expired records still present after clear_expired ran.",
    ["token_type"],
)
