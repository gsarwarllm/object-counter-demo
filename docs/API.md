# API

The HTTP API: endpoints, parameters, responses and errors.

**Documentation:** Swagger UI at [http://localhost:5000/docs](http://localhost:5000/docs) (try every endpoint from the browser), and the OpenAPI 3 contract at `/openapi.yaml` ([`docs/openapi.yaml`](openapi.yaml)). The spec is written by hand (contract first); tests check that every documented response, status code included, matches what the app returns.

| Endpoint | Does |
|---|---|
| `POST /object-count` | Detects the objects in an image, adds those at or above the threshold to the running totals, returns this image's counts and the totals |
| `POST /object-predictions` | Returns the predictions at or above the threshold (class, score, box), highest score first; doesn't change the totals |
| `GET /object-counts` | The totals, sorted by class; repeat `object_class` to filter |
| `GET /models` | The served models, their versions, the default, and a running release |
| `GET /health` | Liveness: `{"status":"ok"}`, no dependencies checked |
| `GET /health/ready` | Readiness: `200`, or `503` if the count store or a model version isn't ready; the Compose healthcheck uses it |
| `GET /metrics` | Prometheus metrics (not part of the contract) |

```bash
curl -F "threshold=0.9" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-count
curl -F "threshold=0.5" -F "model_name=acme_shelf_detector" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-predictions
curl "http://localhost:5000/object-counts?object_class=cat&object_class=dog"
```

The two image endpoints take `threshold` (optional, `0`–`1`, default `0.5`, inclusive), `file` (JPEG or PNG) and `model_name` (optional, default: the manifest's `default_model`). Responses include the model that answered, e.g. `"model":{"name":"ssd_mobilenet_v2","version":"1"}`. All models add to the same running totals. Errors are [RFC 7807](https://www.rfc-editor.org/rfc/rfc7807) `application/problem+json`:

| Status | When |
|---|---|
| `400` | Missing `file`, `threshold` not a number or outside `0`–`1`, unknown `model_name` (`errors` names the field and lists the models), or a file that isn't a JPEG/PNG image |
| `413` | Upload larger than `MAX_UPLOAD_BYTES` |
| `503` | TF Serving or the count database is unreachable |
| `500` | Unexpected error (details are logged, not returned) |

```json
{"type": "about:blank", "title": "Invalid request", "status": 400, "detail": "Request validation failed",
 "instance": "/object-count", "errors": [{"field": "threshold", "message": "must be between 0.0 and 1.0"}]}
```
