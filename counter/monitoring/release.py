"""Shadow and canary releases (X6): what is being released, and whether a canary may be promoted.

The app exposes model_release_info{model, version, role, mode} on /metrics, so Prometheus (and
the release check) knows which version is the champion and which is the candidate.
`judge` compares their error rate, p95 latency and drift over a window; the promotion itself
still goes through the quality gate of `model_registry.py promote` (X5).
"""

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field

from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

# PSI at or above this is drift (as in counter.monitoring.drift).
DRIFT_PSI = 0.25


@dataclass(frozen=True)
class ReleasedVersion:
    model: str
    version: str
    role: str  # champion | candidate
    mode: str  # off | shadow | canary


class ReleaseCollector(Collector):
    """model_release_info: one series per served version, value 1."""

    def __init__(self, versions: list[ReleasedVersion]) -> None:
        self.__versions = versions

    def collect(self) -> Iterable[Metric]:
        info = GaugeMetricFamily(
            "model_release_info",
            "Served model versions: role champion or candidate, and the release mode",
            labels=["model", "version", "role", "mode"],
        )
        for served in self.__versions:
            info.add_metric([served.model, served.version, served.role, served.mode], 1)
        yield info


@dataclass(frozen=True)
class VersionStats:
    """One version's traffic over the window, from Prometheus."""

    version: str
    requests: float
    errors: float  # outcome unavailable or error (invalid images are the client's fault)
    p95_seconds: float | None
    max_psi: float | None  # None: no baseline or too few images

    @property
    def error_rate(self) -> float:
        return self.errors / self.requests if self.requests else 0.0


@dataclass(frozen=True)
class CanaryLimits:
    min_requests: int = 100
    max_error_rate_increase: float = 0.01  # absolute: 1 percentage point
    max_latency_ratio: float = 1.2  # candidate p95 / champion p95
    max_psi: float = DRIFT_PSI


@dataclass(frozen=True)
class Verdict:
    model: str
    decision: str  # promote | hold | insufficient_data
    champion: VersionStats
    candidate: VersionStats
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self) | {
            "champion": asdict(self.champion) | {"error_rate": self.champion.error_rate},
            "candidate": asdict(self.candidate) | {"error_rate": self.candidate.error_rate},
        }


def judge(
    model: str, champion: VersionStats, candidate: VersionStats, limits: CanaryLimits
) -> Verdict:
    """promote only if the candidate had enough traffic and stayed within every limit."""
    if candidate.requests < limits.min_requests:
        return Verdict(
            model,
            "insufficient_data",
            champion,
            candidate,
            [f"candidate served {candidate.requests:.0f} of {limits.min_requests} requests"],
        )
    reasons = []
    if candidate.error_rate > champion.error_rate + limits.max_error_rate_increase:
        reasons.append(
            f"error rate {candidate.error_rate:.2%} vs champion {champion.error_rate:.2%}"
        )
    if (
        candidate.p95_seconds is not None
        and champion.p95_seconds
        and candidate.p95_seconds > champion.p95_seconds * limits.max_latency_ratio
    ):
        reasons.append(
            f"p95 latency {candidate.p95_seconds:.3f} s vs champion {champion.p95_seconds:.3f} s"
        )
    if candidate.max_psi is not None and candidate.max_psi >= limits.max_psi:
        reasons.append(f"drift: PSI {candidate.max_psi:.2f} >= {limits.max_psi}")
    return Verdict(model, "hold" if reasons else "promote", champion, candidate, reasons)
