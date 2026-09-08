"""In-process Prometheus text-exposition metrics (hand-rolled, no prometheus_client)."""

from collections import defaultdict

# Standard latency buckets (seconds) — same defaults prometheus_client ships.
_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0)

# Safe without locks: single-process asyncio event loop (uvicorn main:app,
# no worker forking per Dockerfile CMD) — no preemptive thread interleaving
# between a dict increment and its read.
_requests_total: dict[tuple[str, str, str], int] = defaultdict(int)
_duration_bucket_counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * len(_BUCKETS))
_duration_sum: dict[tuple[str, str], float] = defaultdict(float)
_duration_count: dict[tuple[str, str], int] = defaultdict(int)


def record_request(provider: str, model: str, status: str, duration_s: float) -> None:
    """Record one completed request's outcome and latency for /metrics exposition."""
    _requests_total[(provider, model, status)] += 1
    key = (provider, model)
    _duration_sum[key] += duration_s
    _duration_count[key] += 1
    buckets = _duration_bucket_counts[key]
    for i, upper in enumerate(_BUCKETS):
        if duration_s <= upper:
            buckets[i] += 1


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render() -> str:
    """Render all recorded metrics as Prometheus text exposition format v0.0.4."""
    lines = [
        "# HELP gateway_requests_total Total chat completion requests.",
        "# TYPE gateway_requests_total counter",
    ]
    for (provider, model, status), count in sorted(_requests_total.items()):
        lines.append(
            f'gateway_requests_total{{provider="{_escape(provider)}",'
            f'model="{_escape(model)}",status="{_escape(status)}"}} {count}'
        )
    lines += [
        "# HELP gateway_request_duration_seconds Request latency in seconds.",
        "# TYPE gateway_request_duration_seconds histogram",
    ]
    for provider, model in sorted(_duration_count):
        key = (provider, model)
        buckets = _duration_bucket_counts[key]
        for i, upper in enumerate(_BUCKETS):
            # buckets[i] is already the cumulative le=upper count — record_request
            # increments every bucket whose upper bound the duration falls under,
            # so no further running-sum accumulation belongs here (re-summing
            # would double-count and make bucket values grow past the true total).
            lines.append(
                f'gateway_request_duration_seconds_bucket{{provider="{_escape(provider)}",'
                f'model="{_escape(model)}",le="{upper}"}} {buckets[i]}'
            )
        lines.append(
            f'gateway_request_duration_seconds_bucket{{provider="{_escape(provider)}",'
            f'model="{_escape(model)}",le="+Inf"}} {_duration_count[key]}'
        )
        lines.append(
            f'gateway_request_duration_seconds_sum{{provider="{_escape(provider)}",'
            f'model="{_escape(model)}"}} {_duration_sum[key]}'
        )
        lines.append(
            f'gateway_request_duration_seconds_count{{provider="{_escape(provider)}",'
            f'model="{_escape(model)}"}} {_duration_count[key]}'
        )
    return "\n".join(lines) + "\n"
