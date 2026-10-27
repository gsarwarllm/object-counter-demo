from unittest.mock import Mock

import pytest
from prometheus_client import REGISTRY

from counter.domain.errors import DetectorUnavailableError, InvalidImageError
from counter.entrypoints.routing import ModelRoutes, Route


def route(version):
    return Route(version, Mock(), Mock())


def fallbacks(version):
    labels = {"model": "m", "version": version}
    return REGISTRY.get_sample_value("canary_fallbacks_total", labels) or 0.0


def answer(route):
    return f"answer from {route.version}"


def test_without_a_canary_the_champion_answers():
    champion = route("1")

    assert ModelRoutes("m", champion).run(answer) == ("answer from 1", champion)


@pytest.mark.parametrize(("draw", "expected"), [(0.0, "2"), (0.099, "2"), (0.1, "1"), (0.9, "1")])
def test_canary_percent_of_requests_go_to_the_candidate(draw, expected):
    routes = ModelRoutes("m", route("1"), route("2"), canary_percent=10, draw=lambda: draw)

    result, used = routes.run(answer)

    assert used.version == expected
    assert result == f"answer from {expected}"


def test_zero_percent_never_and_hundred_percent_always_use_the_candidate():
    never = ModelRoutes("m", route("1"), route("2"), canary_percent=0, draw=lambda: 0.0)
    always = ModelRoutes("m", route("1"), route("2"), canary_percent=100, draw=lambda: 0.999)

    assert never.run(answer)[1].version == "1"
    assert always.run(answer)[1].version == "2"


def test_an_unavailable_candidate_falls_back_to_the_champion():
    before = fallbacks("5")
    routes = ModelRoutes("m", route("1"), route("5"), canary_percent=100)

    def call(route):
        if route.version == "5":
            raise DetectorUnavailableError("down")
        return "champion"

    assert routes.run(call)[0] == "champion"
    assert fallbacks("5") == before + 1


def test_other_candidate_errors_are_not_hidden():
    routes = ModelRoutes("m", route("1"), route("2"), canary_percent=100)

    def call(route):
        raise InvalidImageError("not an image")

    with pytest.raises(InvalidImageError):
        routes.run(call)
