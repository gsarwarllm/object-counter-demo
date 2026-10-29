NielsenIQ Innovation Enablement
Homework

Introduction
We appreciate the effort of doing this exercise. If you have any trouble or challenge solving
this during the agreed time window, just let us know so we can find a solution.

Assignment
We’ve built an application that receives an image and a threshold and

● detects the objects in the image,

● counts those whose confidence score is above the given threshold, grouped by their
class (cat, cup, racket, ...) and

● returns the number of objects by class and the accumulated total.

The source code of this application can be shared via a zip folder or GitHub creating a fork
of this repository.

https://github.com/arenan02/object-counter

The assignment consists in performing the following tasks:

   1. Add a new service endpoint to receive the image and the desired threshold and
      return the list of predictions.
   2. Write a new adapter for ObjectCountRepo to persist data using a relational (MySQL
      or PostgreSQL) database.
   3. Review the rest of the source code and propose some improvements that you
      would make in the code, the setup instructions, the tests,...
   4. Implement at least one of the proposed improvements.
   5. If we want to use multiple models trained internally (not public), what would you
      change in the setup of the project?
   6. Choose one of the following
           a. Improve the testing by adding integration and e2e tests (or any other
               improvements you consider necessary)
           b. Support models for object detection using different deep learning
               frameworks. If the task seems too big, just lay out the main key points of the
               proposed solution.

Evaluation
Things that we evaluate and take into consideration about this test.

•   At least 3 of the exercises have been correctly solved.
•   The code is easy to understand following Clean code You can use these rules as a
    Reference)
•   The setup is automated and smoothly reproducible.
    o README.md is present and specifies how to set up the application.
    o Those instructions are enough to run the application in a local environment.
    o The instructions specify every task needed (download additional resources,
       run, test, admin scripts,...)
    o If 2 steps can be automated as one using a task manager (e.g. Makefile), this
       is preferred to write 2 commands in the README file.
•   Additional documentation is well written (precision, correctness,...)

Post-homework interview
A panel of two or three NielsenIQ associates will evaluate the candidate to ask for

•   Explaining his/her homework and the decisions made,
•   Give/receive feedback,
•   Discuss and reason about related topics during the conversation.

---

## Implementation status (added by the candidate)

The assignment text above is unchanged. This repository is the fork: https://github.com/gsarwarllm/object-counter-demo. This section tracks what has been delivered; details are in [`README.md`](README.md), [`docs/ANSWERS.md`](docs/ANSWERS.md), and [`plan.md`](plan.md).

| Task | Status | Delivered | Commit |
|---|---|---|---|
| 1. Endpoint returning the list of predictions | ✅ Done | `POST /object-predictions`: predictions with score ≥ threshold, sorted by score, totals unchanged, problem+json errors. Optional `model_name` since Task 5. | [06fb3f7](https://github.com/gsarwarllm/object-counter-demo/commit/06fb3f7fb1579707c5d8d6cba30a74c6e23443ec) |
| 2. Relational database adapter for `ObjectCountRepo` | ✅ Done | `CountPostgresRepo` (PostgreSQL 16, atomic `INSERT ... ON CONFLICT DO UPDATE`), chosen with `COUNT_REPO=postgres`; the same contract tests run against the memory, MongoDB and PostgreSQL repos | [038a0fe](https://github.com/gsarwarllm/object-counter-demo/commit/038a0fe732a4c380f4844fd72bb357a8c2f4818a) |
| 3. Review the code and propose improvements | ✅ Done | 33 findings (R1–R33) with problem, impact, fix and status in `docs/ANSWERS.md` | [29b95e8](https://github.com/gsarwarllm/object-counter-demo/commit/29b95e85da99ab7241ef2adbd3eda5b367ad2b23) |
| 4. Implement at least one improvement | ✅ Done | 31 of 33 implemented, 1 partly; validation and problem+json errors, image decoding, TF Serving and MongoDB hardening, debug images out of the domain, explicit config, dependency lock files, type hints checked by mypy in CI | [08e7b11](https://github.com/gsarwarllm/object-counter-demo/commit/08e7b118c709c95e13d1db1b3ce2322391edd0d7), plus CI and setup in [962e45a](https://github.com/gsarwarllm/object-counter-demo/commit/962e45a154ada74a41a54b58722d3ff6ce989a05), [8737fbd](https://github.com/gsarwarllm/object-counter-demo/commit/8737fbd3cd7fd2a15f9bffc4435ec4f3deb939ed) and [038a0fe](https://github.com/gsarwarllm/object-counter-demo/commit/038a0fe732a4c380f4844fd72bb357a8c2f4818a), and the follow-ups [2a7f0c4](https://github.com/gsarwarllm/object-counter-demo/commit/2a7f0c41b00bc7f0ce956ca553155027c0c21caf) |
| 5. Multiple internally trained models | ✅ Done | Written answer, and an implementation: model manifest, detector factory and registry, `model_name` and `GET /models`, a local MLflow model registry (publish, promote, pull) with two models | [commit 1eb62f3](https://github.com/gsarwarllm/object-counter-demo/commit/1eb62f3adeab4513d11c46c68d6acd245e94b04a) |
| 6. (a) Integration and e2e tests / (b) multiple frameworks | ✅ (a) done, (b) outlined | (a) 400 tests at every level: integration against real PostgreSQL and MongoDB and over HTTP against a stub TF Serving, end-to-end tests against the Docker stack with the real models (in CI, with MongoDB and PostgreSQL), OpenAPI contract tests, 96% coverage; strategy in [`docs/TESTING.md`](docs/TESTING.md). (b) Outline (not built): one KServe v2 adapter per protocol for Triton Inference Server and OpenVINO Model Server, per-model pre/post-processing in the manifest, model conversion, testing and trade-offs, with an architecture diagram; see [`docs/ANSWERS.md`](docs/ANSWERS.md#task-6b-multiple-deep-learning-frameworks-outline). | (a) [b29b372](https://github.com/gsarwarllm/object-counter-demo/commit/b29b372b1c2bc28a2736b535675ace815c7eaee3), plus [038a0fe](https://github.com/gsarwarllm/object-counter-demo/commit/038a0fe732a4c380f4844fd72bb357a8c2f4818a), [7f2e1fd](https://github.com/gsarwarllm/object-counter-demo/commit/7f2e1fd64e17dfd8c4a4a1220c01b57bdd1d58e4); (b) [5e7fb84](https://github.com/gsarwarllm/object-counter-demo/commit/5e7fb846ffa5c5b2b9631ea4751b7e8a71c20458) |

| Evaluation criterion | Status |
|---|---|
| At least 3 exercises solved | ✅ Tasks 1–5 and 6(a), plus the 6(b) outline |
| Clean code | ✅ Hexagonal layers (the domain has no I/O), ruff lint and format in CI |
| Automated, reproducible setup | ✅ `make setup && make test`; `make install && make start` (earlier: `make setup-models && make models && make up && make run-prod`); GitHub Codespaces; Docker Compose, `.env.example`, README built around `make` ([038a0fe](https://github.com/gsarwarllm/object-counter-demo/commit/038a0fe732a4c380f4844fd72bb357a8c2f4818a)) |
| Additional documentation | ✅ README, `docs/ANSWERS.md` (Tasks 3–6, with the 6(b) architecture diagram), `docs/TESTING.md`, OpenAPI 3 contract [`docs/openapi.yaml`](docs/openapi.yaml) with Swagger UI at `/docs` and contract tests ([commit 7f2e1fd](https://github.com/gsarwarllm/object-counter-demo/commit/7f2e1fd64e17dfd8c4a4a1220c01b57bdd1d58e4)) |
