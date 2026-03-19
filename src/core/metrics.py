from __future__ import annotations

from prometheus_client import Counter, Histogram

webhooks_received_total = Counter(
    "webhooks_received_total",
    "Total webhooks received",
    ["source", "event_type"],
)

deliveries_total = Counter(
    "deliveries_total",
    "Total delivery attempts",
    ["status"],
)

delivery_duration_seconds = Histogram(
    "delivery_duration_seconds",
    "Delivery HTTP request duration",
)

