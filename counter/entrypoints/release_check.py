"""Can a model's candidate version be promoted? Compares it with the champion in Prometheus.

    python -m counter.entrypoints.release_check MODEL [--prometheus URL] [--window 1h]

Works during a canary or a shadow release (RELEASE_MODE): in both, the candidate's calls are
recorded under its own version. Prints the verdict as JSON. Exit code 0: promote; 1: hold or not
enough traffic yet; 2: the check couldn't run (no candidate, Prometheus unreachable).
`make canary-promote` runs it and then `model_registry.py promote MODEL candidate`, which still
applies the quality gate.
"""

import argparse
import json
import math
import os
import re
import sys

import requests

from counter.monitoring.release import CanaryLimits, VersionStats, judge

# Model names and windows go into PromQL; only these shapes are accepted.
MODEL_NAME = re.compile(r"[A-Za-z0-9_.-]+")
WINDOW = re.compile(r"[0-9]+[smhd]")
ERROR_OUTCOMES = "unavailable|error"


class CheckError(Exception):
    pass


class Prometheus:
    def __init__(self, url: str, timeout: float = 10.0) -> None:
        self.__url = url.rstrip("/")
        self.__timeout = timeout

    def query(self, query: str) -> list[dict]:
        """An instant query's series: [{"metric": {labels}, "value": [time, "value"]}]."""
        try:
            response = requests.get(
                f"{self.__url}/api/v1/query", params={"query": query}, timeout=self.__timeout
            )
            response.raise_for_status()
            return list(response.json()["data"]["result"])
        except (requests.RequestException, ValueError, KeyError) as error:
            raise CheckError(f"Prometheus query failed: {query}: {error}") from error

    def by_version(self, query: str) -> dict[str, float]:
        """{version: value} for a query whose series have a version label."""
        return {s["metric"]["version"]: float(s["value"][1]) for s in self.query(query)}

    def roles(self, model: str) -> dict[str, str]:
        """role -> version, from the app's model_release_info."""
        series = self.query(f'model_release_info{{model="{model}"}}')
        return {s["metric"]["role"]: s["metric"]["version"] for s in series}


def collect(prometheus: Prometheus, model: str, window: str) -> tuple[VersionStats, VersionStats]:
    roles = prometheus.roles(model)
    if "candidate" not in roles or "champion" not in roles:
        raise CheckError(
            f"{model}: no candidate is being released (model_release_info has {roles or 'nothing'})"
        )
    selector = f'model="{model}"'
    requests_ = prometheus.by_version(
        f"sum by (version) (increase(detector_requests_total{{{selector}}}[{window}]))"
    )
    errors = prometheus.by_version(
        "sum by (version) (increase(detector_requests_total"
        f'{{{selector},outcome=~"{ERROR_OUTCOMES}"}}[{window}]))'
    )
    p95 = prometheus.by_version(
        "histogram_quantile(0.95, sum by (version, le) "
        f"(rate(detector_request_duration_seconds_bucket{{{selector}}}[{window}])))"
    )
    psi = prometheus.by_version(f"max by (version) (model_drift_psi{{{selector}}})")

    def stats(version: str) -> VersionStats:
        return VersionStats(
            version=version,
            requests=requests_.get(version, 0.0),
            errors=errors.get(version, 0.0),
            p95_seconds=_finite(p95.get(version)),
            max_psi=_finite(psi.get(version)),
        )

    return stats(roles["champion"]), stats(roles["candidate"])


def _finite(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None


def main(argv: list[str] | None = None) -> int:
    defaults = CanaryLimits()
    parser = argparse.ArgumentParser(description="Compare a candidate version with the champion")
    parser.add_argument("model")
    parser.add_argument(
        "--prometheus", default=os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    )
    parser.add_argument("--window", default="1h", help="PromQL range, e.g. 30m, 1h, 1d")
    parser.add_argument("--min-requests", type=int, default=defaults.min_requests)
    parser.add_argument(
        "--max-error-rate-increase", type=float, default=defaults.max_error_rate_increase
    )
    parser.add_argument("--max-latency-ratio", type=float, default=defaults.max_latency_ratio)
    parser.add_argument("--max-psi", type=float, default=defaults.max_psi)
    args = parser.parse_args(argv)
    if not MODEL_NAME.fullmatch(args.model):
        parser.error(f"invalid model name {args.model!r}")
    if not WINDOW.fullmatch(args.window):
        parser.error(f"invalid window {args.window!r}; expected e.g. 30m, 1h, 1d")
    limits = CanaryLimits(
        args.min_requests, args.max_error_rate_increase, args.max_latency_ratio, args.max_psi
    )
    try:
        champion, candidate = collect(Prometheus(args.prometheus), args.model, args.window)
    except CheckError as error:
        print(error, file=sys.stderr)
        return 2
    verdict = judge(args.model, champion, candidate, limits)
    print(json.dumps(verdict.to_dict(), indent=2))
    return 0 if verdict.decision == "promote" else 1


if __name__ == "__main__":
    sys.exit(main())
