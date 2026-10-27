"""A stand-in TF Serving REST server for integration tests that don't need Docker.

It answers POST /v1/models/<name>[/versions/<v>]:predict with a recorded response in the
real TF Serving format and GET /v1/models/<name>[/versions/<v>] with the model status,
records each request, and can be told to fail.
"""

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RECORDED_RESPONSE = Path(__file__).parents[1] / "fixtures" / "tfs_predict_response.json"
PREDICT_PATH = re.compile(r"^/v1/models/(?P<name>[\w-]+)(/versions/(?P<version>\d+))?:predict$")
STATUS_PATH = re.compile(r"^/v1/models/(?P<name>[\w-]+)(/versions/(?P<version>\d+))?$")


class StubTFServing:
    def __init__(self):
        self.mode = "ok"  # ok | error | malformed | slow
        self.model_state = "AVAILABLE"  # what GET status reports, e.g. LOADING
        self.slow_seconds = 2.0
        self.requests: list[dict] = []
        self.__server = ThreadingHTTPServer(("127.0.0.1", 0), self.__handler())
        self.__server.daemon_threads = True  # don't wait for a deliberately slow reply
        self.__running = False
        self.__thread = threading.Thread(
            target=self.__server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )

    @property
    def port(self) -> int:
        return self.__server.server_address[1]

    def start(self) -> "StubTFServing":
        self.__thread.start()
        self.__running = True
        return self

    def stop(self):
        if self.__running:
            self.__server.shutdown()
            self.__server.server_close()
            self.__running = False

    def __handler(self):
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                match = STATUS_PATH.match(self.path)
                stub.requests.append({"path": self.path, "match": match, "body": None})
                if match is None:
                    return self.__reply(404, b'{"error": "unknown path"}')
                if stub.mode == "error":
                    return self.__reply(500, b'{"error": "server failed"}')
                status = {"version": match["version"] or "1", "state": stub.model_state}
                return self.__reply(200, json.dumps({"model_version_status": [status]}).encode())

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                match = PREDICT_PATH.match(self.path)
                stub.requests.append({"path": self.path, "match": match, "body": body})
                if match is None:
                    return self.__reply(404, b'{"error": "unknown path"}')
                if stub.mode == "error":
                    return self.__reply(500, b'{"error": "model failed"}')
                if stub.mode == "malformed":
                    return self.__reply(200, b'{"unexpected": true}')
                if stub.mode == "slow":
                    time.sleep(stub.slow_seconds)
                return self.__reply(200, RECORDED_RESPONSE.read_bytes())

            def __reply(self, status: int, payload: bytes):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        return Handler
