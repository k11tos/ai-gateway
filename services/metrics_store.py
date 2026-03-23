METRIC_KEYS = (
    "requests_total",
    "chat_requests",
    "stream_requests",
    "embedding_requests",
    "errors_total",
)

METRICS = {key: 0 for key in METRIC_KEYS}


def increment_metric(metric_key: str) -> None:
    METRICS[metric_key] += 1


def metrics_snapshot() -> dict[str, int]:
    return {key: METRICS[key] for key in METRIC_KEYS}


def reset_metrics() -> None:
    for key in METRIC_KEYS:
        METRICS[key] = 0
