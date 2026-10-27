import pytest
from prometheus_client import CollectorRegistry, generate_latest

from counter.monitoring.release import (
    CanaryLimits,
    ReleaseCollector,
    ReleasedVersion,
    VersionStats,
    judge,
)

LIMITS = CanaryLimits(min_requests=100)


def stats(version, requests=1000, errors=0, p95=0.2, psi=0.05):
    return VersionStats(version, requests, errors, p95, psi)


def test_a_candidate_within_every_limit_is_promoted():
    verdict = judge("m", stats("1"), stats("2", errors=5, p95=0.22), LIMITS)

    assert verdict.decision == "promote"
    assert verdict.reasons == []


def test_too_little_traffic_is_not_judged():
    verdict = judge("m", stats("1"), stats("2", requests=99, errors=99), LIMITS)

    assert verdict.decision == "insufficient_data"
    assert "99 of 100" in verdict.reasons[0]


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (stats("2", errors=30), "error rate 3.00% vs champion 1.00%"),
        (stats("2", p95=0.5), "p95 latency 0.500 s vs champion 0.200 s"),
        (stats("2", psi=0.3), "drift: PSI 0.30"),
    ],
)
def test_a_candidate_outside_a_limit_is_held(candidate, reason):
    verdict = judge("m", stats("1", errors=10), candidate, LIMITS)

    assert verdict.decision == "hold"
    assert any(reason in r for r in verdict.reasons)


def test_missing_latency_or_drift_data_doesnt_block():
    verdict = judge("m", stats("1", p95=None), stats("2", p95=None, psi=None), LIMITS)

    assert verdict.decision == "promote"


def test_verdict_serializes_with_error_rates():
    data = judge("m", stats("1"), stats("2", errors=10), LIMITS).to_dict()

    assert data["candidate"]["error_rate"] == 0.01
    assert data["decision"] == "promote"


def test_release_info_has_one_series_per_served_version():
    registry = CollectorRegistry()
    registry.register(
        ReleaseCollector(
            [
                ReleasedVersion("m", "1", "champion", "canary"),
                ReleasedVersion("m", "2", "candidate", "canary"),
            ]
        )
    )

    text = generate_latest(registry).decode()

    assert 'model_release_info{mode="canary",model="m",role="champion",version="1"} 1.0' in text
    assert 'model_release_info{mode="canary",model="m",role="candidate",version="2"} 1.0' in text
