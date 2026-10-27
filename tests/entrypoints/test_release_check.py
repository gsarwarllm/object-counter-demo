"""The release check against a stub Prometheus HTTP API (no Prometheus needed)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from counter.entrypoints import release_check

ROLES = [("champion", "1"), ("candidate", "2")]


class StubPrometheus:
    """Answers /api/v1/query: each instant query is matched by a substring of its PromQL."""

    def __init__(self, answers):
        self.answers = answers  # [(substring, {version: value})], first match wins
        self.queries = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = parse_qs(urlparse(self.path).query)["query"][0]
                stub.queries.append(query)
                body = json.dumps({"status": "success", "data": {"result": stub.result(query)}})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def result(self, query):
        if query.startswith("model_release_info"):
            return [
                {"metric": {"role": role, "version": version}, "value": [0, "1"]}
                for role, version in self.answers.get("roles", ROLES)
            ]
        for substring, values in self.answers["series"]:
            if substring in query:
                return [
                    {"metric": {"version": version}, "value": [0, str(value)]}
                    for version, value in values.items()
                ]
        return []


@pytest.fixture
def prometheus(request):
    stub = StubPrometheus(request.param)
    yield stub
    stub.server.shutdown()


HEALTHY = {
    "series": [
        ('outcome=~"unavailable|error"', {"1": 2, "2": 1}),
        ("increase(detector_requests_total", {"1": 900, "2": 150}),
        ("histogram_quantile", {"1": 0.2, "2": 0.21}),
        ("model_drift_psi", {"1": 0.02, "2": "NaN"}),
    ]
}
SLOW = {
    "series": [
        ("increase(detector_requests_total", {"1": 900, "2": 150}),
        ("histogram_quantile", {"1": 0.2, "2": 0.9}),
    ]
}


@pytest.mark.parametrize("prometheus", [HEALTHY], indirect=True)
def test_a_healthy_candidate_may_be_promoted(prometheus, capsys):
    code = release_check.main(["m", "--prometheus", prometheus.url, "--window", "30m"])

    verdict = json.loads(capsys.readouterr().out)
    assert code == 0
    assert verdict["decision"] == "promote"
    assert verdict["candidate"] == {
        "version": "2",
        "requests": 150.0,
        "errors": 1.0,
        "error_rate": pytest.approx(1 / 150),
        "p95_seconds": 0.21,
        "max_psi": None,  # NaN: not enough images for drift yet
    }
    assert all('model="m"' in query for query in prometheus.queries)
    assert any("[30m]" in query for query in prometheus.queries)


@pytest.mark.parametrize("prometheus", [SLOW], indirect=True)
def test_a_slow_candidate_is_held(prometheus, capsys):
    code = release_check.main(["m", "--prometheus", prometheus.url])

    assert code == 1
    assert json.loads(capsys.readouterr().out)["decision"] == "hold"


@pytest.mark.parametrize("prometheus", [HEALTHY], indirect=True)
def test_not_enough_traffic_is_not_a_promotion(prometheus, capsys):
    code = release_check.main(["m", "--prometheus", prometheus.url, "--min-requests", "1000"])

    assert code == 1
    assert json.loads(capsys.readouterr().out)["decision"] == "insufficient_data"


@pytest.mark.parametrize(
    "prometheus", [{"roles": [("champion", "1")], "series": []}], indirect=True
)
def test_without_a_candidate_the_check_cant_run(prometheus, capsys):
    code = release_check.main(["m", "--prometheus", prometheus.url])

    assert code == 2
    assert "no candidate is being released" in capsys.readouterr().err


def test_unreachable_prometheus_is_reported(capsys):
    code = release_check.main(["m", "--prometheus", "http://127.0.0.1:1"])

    assert code == 2
    assert "Prometheus query failed" in capsys.readouterr().err


@pytest.mark.parametrize("args", [['m"}) or vector(1'], ["m", "--window", "1h]) or vector(1"]])
def test_arguments_cant_inject_promql(args):
    with pytest.raises(SystemExit) as exit_info:
        release_check.main([*args, "--prometheus", "http://127.0.0.1:1"])

    assert exit_info.value.code == 2
