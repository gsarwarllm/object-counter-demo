# Test every task, step by step

A walkthrough that tests every task of the assignment and every extra feature against the real models, with the result to expect after each command. Run it **line by line**, in order: paste a line, press Enter, and wait for the prompt (`$`) to come back. Expected answers are shown as the app prints them (compact JSON without spaces, e.g. `"status":"ok"`), so you can look for them in the output.

**Before you start:** do [`SETUP.md`](SETUP.md) up to Part D step 1 (`make install` ends with `Ready`), or open a [codespace](SETUP.md#fastest-github-codespaces-nothing-to-install), where that already happened (open the `localhost` links below through its **Ports** tab). Docker must be running (on Windows: Docker Desktop says *Engine running*; every command goes into the **Ubuntu** window, not PowerShell and not Docker Desktop's own terminal).

**Two terminals.** **Terminal 1** runs the app: it keeps printing log lines and the prompt doesn't come back until you press **Ctrl+C**. **Terminal 2** sends the requests. Open each one (Windows: Start → type `Ubuntu` → Enter; Linux: **Ctrl+Alt+T**) and start with:

```bash
cd ~/object-counter-demo
```

Totals stored by earlier runs only make the numbers larger; they don't break any step. It takes about 45 minutes.

| Part | Tests | Steps |
|---|---|---|
| [Stage 1: quick check without Docker](#stage-1-quick-check-without-docker) | dev mode with the fake model | 1–5 |
| [Stage 2: start the real app](#stage-2-start-the-real-app) | health, models, API docs, counting | 6–14 |
| [Task 1: predictions endpoint](#task-1-predictions-endpoint) | `POST /object-predictions`, thresholds, invalid input | 15–19 |
| [Task 2: PostgreSQL adapter](#task-2-postgresql-adapter) | counts in MongoDB, then in PostgreSQL | 20–23 |
| [Task 3: code review](#task-3-code-review) | written answer | 24 |
| [Task 4: improvements](#task-4-improvements) | every error response, request IDs, metrics, failing dependencies, logs, debug images, CLI, quality checks | 25–41 |
| [Task 5: multiple models](#task-5-multiple-models) | model choice, model registry | 42–45 |
| [Beyond the assignment](#beyond-the-assignment) | baselines, quality gate, dashboards, shadow and canary releases, drift | 46–71 |
| [Task 6: tests](#task-6-tests) | end-to-end, integration, registry and unit tests | 72–79 |
| [Stop everything](#stop-everything) | | 80 |

## Stage 1: quick check without Docker

Dev mode runs the app with a **fake** model (always one cat, version `null`) and counts kept in memory. It shows the API works before anything real is involved; [the README explains what it can't show](ARCHITECTURE.md#dev-or-prod-what-each-mode-really-runs).

1. Terminal 1. The fast tests (about 20 seconds). The last line should say `... passed, 1 skipped`:

   ```bash
   make test
   ```

2. Terminal 1. Start the dev server and leave it running:

   ```bash
   make run
   ```

3. Terminal 2. Count a picture. Expect `"current_objects":[{"count":1,"object_class":"cat"}]` and `"model":{"name":"ssd_mobilenet_v2","version":null}`:

   ```bash
   curl -F "threshold=0.5" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-count
   ```

4. Terminal 2. Count a different picture: it still finds one cat, because the fake model ignores the image:

   ```bash
   curl -F "threshold=0.5" -F "file=@resources/images/food.jpg" http://localhost:5000/object-count
   ```

5. Terminal 1. Press **Ctrl+C**. The counts are gone with the process: dev mode keeps nothing.

## Stage 2: start the real app

6. Terminal 1. Check the machine. The last line should say `Ready`:

   ```bash
   make doctor
   ```

7. Terminal 1. Start the services (TF Serving with both models, MongoDB, PostgreSQL), then the app with counts in MongoDB. It shows three `Healthy` lines, then the app's first log line `Serving models ssd_mobilenet_v2@1, acme_shelf_detector@1 ... count repo=CountMongoDBRepo`, and keeps running:

   ```bash
   make start
   ```

8. Terminal 2. Liveness, expect `{"status":"ok"}`:

   ```bash
   curl http://localhost:5000/health
   ```

9. Readiness, expect `"repository":"ok"`, both detectors `"ok"` and `"status":"ok"`:

   ```bash
   curl http://localhost:5000/health/ready
   ```

10. The API contract, expect `openapi: 3.0.3` and `title: Object Counter API`:

    ```bash
    curl -s http://localhost:5000/openapi.yaml | head -3
    ```

11. In the browser, open [http://localhost:5000/docs](http://localhost:5000/docs): the Swagger UI lists every endpoint (*Try it out* sends a real request).

12. The totals so far (`{"total_objects":[]}` on a fresh installation):

    ```bash
    curl http://localhost:5000/object-counts
    ```

13. Count three sample pictures at threshold 0.9 (the original endpoint). Expect `current_objects` per picture (`person`; `cat`; `cup` and `bowl`), `"model":{"name":"ssd_mobilenet_v2","version":"1"}`, and the growing `total_objects`. The first request takes about 5 seconds:

    ```bash
    curl -F "threshold=0.9" -F "file=@resources/images/boy.jpg" http://localhost:5000/object-count
    curl -F "threshold=0.9" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-count
    curl -F "threshold=0.9" -F "file=@resources/images/food.jpg" http://localhost:5000/object-count
    ```

14. The totals again, now higher and sorted by class; then only `cat` and `dog` (`dog` is left out because it was never counted):

    ```bash
    curl http://localhost:5000/object-counts
    curl "http://localhost:5000/object-counts?object_class=cat&object_class=dog"
    ```

## Task 1: predictions endpoint

15. Terminal 2. The predictions for one picture, without changing the totals. Expect `{"count":5,"model":{"name":"ssd_mobilenet_v2","version":"1"},"predictions":[...],"threshold":0.5}`: each prediction has a `box` (`xmin`, `ymin`, `xmax`, `ymax` between 0 and 1), a `class_name` and a `score`, highest score first:

    ```bash
    curl -F "threshold=0.5" -F "file=@resources/images/food.jpg" http://localhost:5000/object-predictions
    ```

16. The threshold decides what's included (inclusive): at 0.9 expect `"count":2` (cup, bowl), at 0.3 `"count":7`, and without a threshold the default `"threshold":0.5`:

    ```bash
    curl -F "threshold=0.9" -F "file=@resources/images/food.jpg" http://localhost:5000/object-predictions
    curl -F "threshold=0.3" -F "file=@resources/images/food.jpg" http://localhost:5000/object-predictions
    curl -F "file=@resources/images/food.jpg" http://localhost:5000/object-predictions
    ```

17. A threshold outside 0–1 is rejected. Expect a problem+json body with `"field":"threshold","message":"must be between 0.0 and 1.0"`, then `400`:

    ```bash
    curl -w '\n%{http_code}\n' -F "threshold=2" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-predictions
    ```

18. No file. Expect `"field":"file","message":"is required"` and `400`:

    ```bash
    curl -w '\n%{http_code}\n' -F "threshold=0.5" http://localhost:5000/object-predictions
    ```

19. In the browser: [http://localhost:5000/docs](http://localhost:5000/docs) → **POST /object-predictions** → **Try it out** → *file*: **Choose File** → **Execute**.

## Task 2: PostgreSQL adapter

20. Terminal 2. By default the counts are in MongoDB. Expect the same totals as step 14:

    ```bash
    docker compose exec -T mongo mongosh --quiet prod_counter --eval 'db.counter.find({}, {_id: 0}).sort({object_class: 1}).toArray()'
    ```

21. Terminal 1. Press **Ctrl+C**, then start the app with PostgreSQL as the count store (the services keep running). Its first log line now says `count repo=CountPostgresRepo`:

    ```bash
    COUNT_REPO=postgres make run-prod
    ```

22. Terminal 2. Count a picture, then look inside the table. Expect the rows `object_class | count | updated_at` with `cat` and `car`; send the same picture again and both counts go up by one:

    ```bash
    curl -F "threshold=0.5" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-count
    docker compose exec -T postgres psql -U counter -d counter -c "SELECT * FROM object_counts ORDER BY object_class;"
    ```

23. The totals through the API now come from PostgreSQL:

    ```bash
    curl http://localhost:5000/object-counts
    ```

## Task 3: code review

24. Nothing to run. Read [`ANSWERS.md`](ANSWERS.md#task-3-code-review-and-proposed-improvements), *Task 3*: 33 findings (R1–R33), each with the problem, its impact, the fix and its status.

## Task 4: improvements

The app from step 21 (counts in PostgreSQL) keeps running in terminal 1. All commands go into terminal 2. Each error prints a problem+json body (RFC 7807), then the HTTP status.

25. Threshold not a number. Expect `"message":"must be a number"` and `400`:

    ```bash
    curl -w '\n%{http_code}\n' -F "threshold=high" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-count
    ```

26. A file that isn't an image. Expect `"title":"Invalid image"`, `file must be a JPEG or PNG image` and `400`:

    ```bash
    curl -w '\n%{http_code}\n' -F "file=@README.md" http://localhost:5000/object-count
    ```

27. An upload over 10 MB. Expect `Uploads are limited to 10485760 bytes` and `413`:

    ```bash
    head -c 11000000 /dev/zero > /tmp/big.jpg
    curl -w '\n%{http_code}\n' -F "file=@/tmp/big.jpg" http://localhost:5000/object-count
    rm /tmp/big.jpg
    ```

28. An empty class filter (`must not be empty`, `400`) and an unknown path (`404`):

    ```bash
    curl -w '\n%{http_code}\n' "http://localhost:5000/object-counts?object_class="
    curl -w '\n%{http_code}\n' http://localhost:5000/nothing-here
    ```

29. Your own request ID. The response header repeats it, and terminal 1 shows it in that request's log line (`[my-test-1] ... ssd_mobilenet_v2@1 returned 2 detections in ... ms`):

    ```bash
    curl -s -i -H "X-Request-ID: my-test-1" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-predictions | grep -i x-request-id
    ```

30. The Prometheus metrics. Expect `http_requests_total` per route and status (including the 400s and the 413 above), `detector_requests_total` per model and version, and `objects_counted_total` per class:

    ```bash
    curl -s http://localhost:5000/metrics | grep -E "^(http_requests_total|detector_requests_total|objects_counted_total)"
    ```

31. The prediction log in PostgreSQL: one row per successful model call, per model and version:

    ```bash
    docker compose exec -T postgres psql -U counter -d counter -c "SELECT model, version, count(*) AS predictions, max(logged_at) AS last FROM prediction_logs GROUP BY model, version ORDER BY model;"
    ```

32. Stop the database:

    ```bash
    docker compose stop postgres
    ```

33. Counting now fails with `"title":"Count repository unavailable"` and `503`; predictions still work (`200`, they don't need the database); readiness reports `"repository":"unavailable"` and `503`:

    ```bash
    curl -w '\n%{http_code}\n' -F "file=@resources/images/cat.jpg" http://localhost:5000/object-count
    curl -s -o /dev/null -w '%{http_code}\n' -F "file=@resources/images/cat.jpg" http://localhost:5000/object-predictions
    curl -w '\n%{http_code}\n' http://localhost:5000/health/ready
    ```

34. Start it again. After a few seconds readiness is back to `"status":"ok"` and `200`, without restarting the app:

    ```bash
    docker compose start postgres
    sleep 5
    curl -w '\n%{http_code}\n' http://localhost:5000/health/ready
    ```

35. Stop TF Serving. Predictions fail with `"title":"Object detector unavailable"` and `503`, readiness shows both detectors `"unavailable"`; reading the totals still works (`200`):

    ```bash
    docker compose stop tfserving
    curl -w '\n%{http_code}\n' -F "file=@resources/images/cat.jpg" http://localhost:5000/object-predictions
    curl -w '\n%{http_code}\n' http://localhost:5000/health/ready
    curl -w '\n%{http_code}\n' http://localhost:5000/object-counts
    ```

36. Start it again and wait until readiness says ok (it loads both models, about 10 seconds; it prints `ready`). The first prediction after a restart can take several seconds; if it answers `503`, send it again:

    ```bash
    docker compose start tfserving
    until curl -sf -o /dev/null http://localhost:5000/health/ready; do sleep 2; done; echo ready
    curl -s -o /dev/null -w '%{http_code}\n' -F "file=@resources/images/cat.jpg" http://localhost:5000/object-predictions
    ```

37. Terminal 1. Press **Ctrl+C**, then start the app with JSON log lines and debug images:

    ```bash
    LOG_FORMAT=json DEBUG_IMAGES=1 make run-prod
    ```

38. Terminal 2. Send a picture, then list the debug images. Terminal 1 prints JSON lines (`"level"`, `"request_id"`, `"message"`); the folder holds `all_predictions.jpg` and `valid_predictions_with_threshold_0.5.jpg`, the picture with its boxes drawn (open them with any image viewer; on Windows `explorer.exe tmp/debug`):

    ```bash
    curl -s -o /dev/null -w '%{http_code}\n' -F "threshold=0.5" -F "file=@resources/images/boy.jpg" http://localhost:5000/object-predictions
    ls tmp/debug
    ```

39. Terminal 1. Press **Ctrl+C**. Then the command-line interface: count a picture without the web server. Expect the same JSON as `/object-count`, ending with `"model": {"name": "ssd_mobilenet_v2", "version": "1"}`:

    ```bash
    ENV=prod .venv/bin/python -m counter.entrypoints.main resources/images/cat.jpg 0.5
    ```

40. Terminal 1. The CLI with the second model, then with an invalid threshold (expect `threshold: must be between 0.0 and 1.0`):

    ```bash
    ENV=prod .venv/bin/python -m counter.entrypoints.main resources/images/cat.jpg 0.5 acme_shelf_detector
    ENV=prod .venv/bin/python -m counter.entrypoints.main resources/images/cat.jpg 5
    ```

41. Terminal 1. The same quality checks as CI: lint, type checks, the API spec, security and the fast tests (about 1 minute; it needs internet for the security audit). It should end with `... passed, 1 skipped` and no `Error`:

    ```bash
    make check
    ```

The written list of improvements is [`ANSWERS.md`](ANSWERS.md#task-4-implemented-improvements), *Task 4*.

## Task 5: multiple models

42. Terminal 1. Start the app again (counts in MongoDB):

    ```bash
    make run-prod
    ```

43. Terminal 2. The served models. Expect `"default_model":"ssd_mobilenet_v2"` and both models with `"version":"1"`:

    ```bash
    curl http://localhost:5000/models
    ```

44. Terminal 2. Pick the second model, then a model that doesn't exist. Expect `"model":{"name":"acme_shelf_detector","version":"1"}`, then `unknown model 'nope'; available: acme_shelf_detector, ssd_mobilenet_v2` and `400`:

    ```bash
    curl -F "threshold=0.5" -F "model_name=acme_shelf_detector" -F "file=@resources/images/boy.jpg" http://localhost:5000/object-predictions
    curl -w '\n%{http_code}\n' -F "model_name=nope" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-predictions
    ```

45. Terminal 1. Press **Ctrl+C**, then open the model registry (MLflow). It needs about 20 seconds to start; then open [http://127.0.0.1:5001](http://127.0.0.1:5001) → *Models*: both models, version 1, alias `champion`. Press **Ctrl+C** when done:

    ```bash
    make mlflow-ui
    ```

The written answer is [`ANSWERS.md`](ANSWERS.md#task-5-multiple-internally-trained-models), *Task 5*.

## Beyond the assignment

**Baselines and the quality gate** (terminal 1; the services from step 7 are still running)

46. Compute the drift baseline of each served version from the sample pictures and store it with the version. Expect `stored the baseline with version 1 in the registry` per model:

    ```bash
    make baseline
    ```

47. Evaluate both champions on the labelled sample set. Expect `F1 0.778` for `ssd_mobilenet_v2` and `F1 0.842` for `acme_shelf_detector` (stored with the version):

    ```bash
    make evaluate MODEL=ssd_mobilenet_v2 VERSION=1
    make evaluate MODEL=acme_shelf_detector VERSION=1
    ```

**Dashboards** (terminal 1)

48. Start the whole stack with the app in a container, Prometheus and Grafana (the first time about 10 minutes; it ends with six `Healthy` lines; on Windows also visible in Docker Desktop):

    ```bash
    make monitoring
    ```

49. Terminal 2. Send 20 requests so the panels have traffic (prints `sent`):

    ```bash
    for i in $(seq 1 20); do curl -s -o /dev/null -F "file=@resources/images/cat.jpg" http://localhost:5000/object-count; done; echo sent
    ```

50. Prometheus: open [http://localhost:9090](http://localhost:9090) → *Status* → *Targets*: `object-counter` and `tfserving` are *UP*. *Alerts* lists `ModelDrift`, `InputDrift`, `HighServerErrorRate`, `DetectorUnavailable` and `CandidateUnhealthy`. From the terminal (expect `"job":"object-counter"`, `"job":"tfserving"` and `"health":"up"` twice):

    ```bash
    curl -s http://localhost:9090/api/v1/targets | grep -o '"job":"[a-z-]*"\|"health":"[a-z]*"'
    ```

51. Grafana: open [http://localhost:3000](http://localhost:3000) → *Dashboards* → **Object Counter**: 11 panels, from *Requests per second by route and status* to *Release: champion vs candidate* (no login needed to view). The app container's own logs: `docker compose logs -f app` (**Ctrl+C** stops watching; the app keeps running).

**Shadow and canary releases** (terminal 2; the stack from step 48 keeps running)

A release needs a second version. As in CI, the weights of the other model stand in for a retrained `acme_shelf_detector`. The registry is backed up first and restored in step 64, so nothing stays changed.

52. Back up the registry, the pulled models and the baselines:

    ```bash
    mkdir -p tmp/backup
    cp -r tmp/mlflow tmp/model tmp/baselines tmp/backup/
    ```

53. Register the stand-in as version 2 (expect `acme_shelf_detector: registered version 2`):

    ```bash
    mkdir -p tmp/candidate
    cp -r tmp/downloads/ssd_mobilenet_v2 tmp/candidate/acme_shelf_detector
    PYTHONPATH=. .venv-models/bin/python scripts/model_registry.py publish --model acme_shelf_detector --downloads tmp/candidate
    ```

54. Make it the candidate and serve it next to the champion (`candidates.lock.json` then shows `"acme_shelf_detector": "2"`):

    ```bash
    make promote-model MODEL=acme_shelf_detector VERSION=2 ALIAS=candidate
    make pull-models
    cat tmp/model/candidates.lock.json
    docker compose restart tfserving
    ```

55. Wait until TF Serving reports both versions `"state":"AVAILABLE"`:

    ```bash
    until curl -sf -o /dev/null http://localhost:8501/v1/models/acme_shelf_detector/versions/2; do sleep 2; done
    curl http://localhost:8501/v1/models/acme_shelf_detector
    ```

56. Quality gate: evaluate version 2 (expect `F1 0.778`), then try to make it the champion. It is **refused**: `candidate F1 0.778 is below the champion's 0.842 (tolerance 0.02)`:

    ```bash
    make evaluate MODEL=acme_shelf_detector VERSION=2
    make promote-model MODEL=acme_shelf_detector VERSION=2
    ```

57. **Shadow release:** restart the app container in shadow mode. `/models` now shows `"release":{"candidate_version":"2","mode":"shadow"}`:

    ```bash
    RELEASE_MODE=shadow docker compose --profile app up -d --wait app
    curl http://localhost:5000/models
    ```

58. Send 10 requests to the model. Every answer comes from the champion (prints `"version":"1"` ten times), while version 2 gets a copy of each in the background:

    ```bash
    for i in $(seq 1 10); do curl -s -F "model_name=acme_shelf_detector" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-predictions | grep -o '"version":"[0-9]*"'; done
    ```

59. The metrics show both versions called 10 times, 10 shadow comparisons and the class agreement:

    ```bash
    curl -s http://localhost:5000/metrics | grep -E '^(detector_requests_total\{model="acme|shadow_requests_total|shadow_class_agreement_sum)'
    ```

60. **Canary release:** restart the app container with half of the traffic to the candidate. `/models` shows `"canary_percent":50.0` and `"mode":"canary"`:

    ```bash
    RELEASE_MODE=canary CANARY_PERCENT=50 docker compose --profile app up -d --wait app
    curl http://localhost:5000/models
    ```

61. Send 250 requests (about 2 minutes) and count which version answered: roughly half each, e.g. `120 "version":"1"` and `130 "version":"2"`:

    ```bash
    for i in $(seq 1 250); do curl -s -F "model_name=acme_shelf_detector" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-predictions | grep -o '"version":"[0-9]*"'; done | sort | uniq -c
    ```

62. Wait 30 seconds for Prometheus to scrape, then ask for a verdict. Expect `"decision": "promote"` (no errors, latency close to the champion's). With fewer than 100 candidate calls it says `insufficient_data`: send more requests (step 61) and repeat:

    ```bash
    sleep 30
    make canary-check MODEL=acme_shelf_detector WINDOW=15m
    ```

63. `make canary-promote` runs the same check and then promotes, but the quality gate still applies: expect the same refusal as in step 56. Grafana's release panels now show champion and candidate side by side:

    ```bash
    make canary-promote MODEL=acme_shelf_detector WINDOW=15m
    ```

64. **Restore** the registry and models from step 52, serve only the champions again, and restart the app container without a release. `candidates.lock.json` shows `{}` and `/models` has no `release` any more:

    ```bash
    rm -rf tmp/mlflow tmp/model tmp/baselines tmp/candidate
    cp -r tmp/backup/mlflow tmp/backup/model tmp/backup/baselines tmp/
    rm -rf tmp/backup
    make pull-models
    cat tmp/model/candidates.lock.json
    docker compose restart tfserving
    docker compose --profile app up -d --wait app
    curl http://localhost:5000/models
    ```

**Drift** (terminal 2)

65. The drift report per served version, comparing recent traffic with each baseline: `stable`, `moderate`, `drift` or `insufficient_data` per feature. With only the three sample pictures as traffic, `drift` is expected:

    ```bash
    make drift
    ```

66. The same numbers as Prometheus gauges:

    ```bash
    curl -s http://localhost:5000/metrics | grep "^model_drift_psi" | head -5
    ```

67. Optional, **deletes the prediction log**: synthetic data that shows every drift state:

    ```bash
    make demo-data RESET=1
    ```

68. The report now shows `ssd_mobilenet_v2` with `drift` on every feature and `acme_shelf_detector` `moderate` for `brightness` and `classes`; the Grafana drift panels follow within 5 minutes:

    ```bash
    make drift
    ```

69. `make demo-data` replaced the baselines in `tmp/baselines/`. Bring the real ones back from the registry:

    ```bash
    make pull-models
    ```

70. Grafana: after 5 minutes reload [http://localhost:3000](http://localhost:3000) → **Object Counter** and scroll to *Prediction drift* and *Input-data drift*: the PSI per model version and feature (0.1 moderate, 0.25 drift).

71. The written design of these features is in [`DECISIONS.md`](DECISIONS.md) and [`../plan.md`](../plan.md) section 10.

## Task 6: tests

**6(a) Integration and end-to-end tests.** How and why each level is tested: [`TESTING.md`](TESTING.md).

72. Terminal 2. The end-to-end tests against the running stack (real models, Prometheus, Grafana; also checks the counts in MongoDB). Expect `20 passed`, nothing skipped:

    ```bash
    make test-e2e E2E_COUNT_REPO=mongo
    ```

73. Switch the app container to PostgreSQL and run them again. Expect `20 passed`:

    ```bash
    COUNT_REPO=postgres docker compose --profile app up -d --wait app
    make test-e2e E2E_COUNT_REPO=postgres
    ```

74. Stop the stack. The next tests start their own throwaway containers, and on a machine with little RAM they start too slowly while the stack runs:

    ```bash
    make down
    ```

75. The fast tests with a coverage report. Expect `... passed, 1 skipped` and `Required test coverage of 90% reached`:

    ```bash
    make coverage
    ```

76. The repositories against real PostgreSQL and MongoDB in throwaway containers (about 1–3 minutes). Expect `39 passed`:

    ```bash
    make test-integration
    ```

77. The model-registry script against a temporary MLflow registry. Expect `11 passed`:

    ```bash
    make test-models
    ```

78. Optional, everything in one command, as in CI: build and start the whole stack, then the end-to-end tests with the MongoDB check (`20 passed`):

    ```bash
    make e2e E2E_COUNT_REPO=mongo
    ```

79. **6(b) Other ML frameworks** is a written outline: [`ANSWERS.md`](ANSWERS.md#task-6b-multiple-deep-learning-frameworks-outline), *Task 6(b)*.

## Stop everything

80. Stop every container (the counts stay saved for next time); on Windows, then right-click the whale icon in the taskbar → **Quit Docker Desktop** to free the memory:

    ```bash
    make down
    ```

If something goes wrong: run `make doctor`, and see [Troubleshooting](SETUP.md#troubleshooting).

Measured on an Ubuntu 26.04 VM with 2 CPUs and 5 GB RAM (2026-10-28).
