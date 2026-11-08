"""Latency metrics shared by every eval: distribution stats over milliseconds."""
import statistics
import time
from contextlib import contextmanager


def percentile(sorted_ms: list[float], p: float) -> float:
    """Nearest-rank percentile of an ascending list."""
    if not sorted_ms:
        return float("nan")
    k = max(0, min(len(sorted_ms) - 1, int(round(p / 100 * len(sorted_ms) + 0.5)) - 1))
    return sorted_ms[k]


def latency_stats(values_ms) -> dict | None:
    """{n, mean, p50, p90, p95, p99, max} in ms (rounded), or None if empty."""
    xs = sorted(float(v) for v in values_ms if v is not None)
    if not xs:
        return None
    return {"n": len(xs), "mean": round(statistics.fmean(xs)), "p50": round(percentile(xs, 50)),
            "p90": round(percentile(xs, 90)), "p95": round(percentile(xs, 95)),
            "p99": round(percentile(xs, 99)), "max": round(xs[-1])}


@contextmanager
def timer(out: dict, key: str):
    """with timer(row, "retrieve_ms"): ...  -> row["retrieve_ms"] = elapsed ms."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        out[key] = round((time.perf_counter() - t0) * 1000, 1)


def fmt_stats(s: dict | None) -> str:
    if not s:
        return "n/a"
    return f"p50 {s['p50']} · p95 {s['p95']} · mean {s['mean']} · max {s['max']} ms (n={s['n']})"
