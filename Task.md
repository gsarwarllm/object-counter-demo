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

https://github.com/gsarwarllm/object-counter-vibe-coding.git

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

The assignment text above is unchanged. This section tracks what has been delivered; details are in [`README.md`](README.md), [`docs/ANSWERS.md`](docs/ANSWERS.md), [`plan.md`](plan.md) and [`completion.pdf`](completion.pdf).

| Task | Status | Delivered | Pull request |
|---|---|---|---|
| 1. Endpoint returning the list of predictions | ✅ Done | `POST /object-predictions`: predictions with score ≥ threshold, sorted by score, totals unchanged, problem+json errors. Optional `model_name` since Task 5. | [#3](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/3) |
| 2. Relational database adapter for `ObjectCountRepo` | ✅ Done | `CountPostgresRepo` (PostgreSQL 16, atomic `INSERT ... ON CONFLICT DO UPDATE`), chosen with `COUNT_REPO=postgres`; the same contract tests run against the memory, MongoDB and PostgreSQL repos | [#9](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/9) |
| 3. Review the code and propose improvements | ✅ Done | 33 findings (R1–R33) with problem, impact, fix and status in `docs/ANSWERS.md` | [#10](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/10) |
| 4. Implement at least one improvement | ✅ Done | 26 of 33 implemented, 1 partly; validation and problem+json errors, image decoding, TF Serving and MongoDB hardening, debug images out of the domain, explicit config | [#11](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/11), plus #2, #6, #8, #9 |
| 5. Multiple internally trained models | ✅ Done | Written answer, and an implementation: model manifest, detector factory and registry, `model_name` and `GET /models`, a local MLflow model registry (publish, promote, pull) with two models | [PR #13](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/13) |
| 6. (a) Integration and e2e tests / (b) multiple frameworks | ✅ (a) done, (b) outlined | (a) 161 tests at every level: integration against real PostgreSQL and MongoDB and over HTTP against a stub TF Serving, end-to-end tests against the Docker stack with the real models (in CI, with MongoDB and PostgreSQL), OpenAPI contract tests, 98% coverage; strategy in [`docs/TESTING.md`](docs/TESTING.md). (b) Outline (not built): one KServe v2 adapter per protocol for Triton Inference Server and OpenVINO Model Server, per-model pre/post-processing in the manifest, model conversion, testing and trade-offs, with an architecture diagram; see [`docs/ANSWERS.md`](docs/ANSWERS.md#task-6b-multiple-deep-learning-frameworks-outline). | (a) [#15](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/15), plus [#9](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/9), [#14](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/14); (b) [#16](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/16) |

| Evaluation criterion | Status |
|---|---|
| At least 3 exercises solved | ✅ Tasks 1–5 and 6(a), plus the 6(b) outline |
| Clean code | ✅ Hexagonal layers (the domain has no I/O), ruff lint and format in CI |
| Automated, reproducible setup | ✅ `make setup && make test`; `make setup-models && make models && make up && make run-prod`; Docker Compose, `.env.example`, README built around `make` ([#8](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/8)) |
| Additional documentation | ✅ README, `docs/ANSWERS.md` (Tasks 3–6, with the 6(b) architecture diagram), `docs/TESTING.md`, OpenAPI 3 contract [`docs/openapi.yaml`](docs/openapi.yaml) with Swagger UI at `/docs` and contract tests ([PR #14](https://github.com/gsarwarllm/object-counter-vibe-coding/pull/14)) |
