# Visual Recommendations MVP

Async FastAPI service for generating and evaluating improved marketing creatives
from structured recommendations and brand guidelines.

## Quick overview

- **Try it:** Start the service, open Swagger UI, and submit the supplied sample
  files to `POST /api/v1/tasks`.
- **Workflow:** Generate from the original → evaluate all checks → repair only
  when required → return the final variant.
- **Implementation:** An async task API, deterministic tests, Docker, and CI.
- **Scope:** A small MVP  , not a full production platform.

## Start the service

Choose one path.

### 1. Docker

Use this path to run the same container that CI builds.

```shell
make docker-build
make docker-run
```

### 2. Local development with uv

Use this path when changing or debugging the application.

```shell
make dev
```

On the first `make docker-run` or `make dev`, Make creates the ignored `.env`
file and tells you to set `OPENAI_API_KEY`. Set it once, then repeat the same
command. Docker users do not need to install `uv`; it is inside the image.

## Submit the supplied sample inputs

- Open [Swagger UI](http://127.0.0.1:8000/docs).
- Submit `POST /api/v1/tasks` with both creatives, `recommendations.json`, and
  `brand_guidelines.json` from [`examples/demo/`](examples/demo/).
- Poll the returned `status_url`, then retrieve each result's `variant_url`.
- The server needs an API key at startup but makes no provider call until task
  submission.

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/tasks` | Submit one or more image uploads and matching JSON files. |
| `GET /api/v1/tasks/{task_id}` | Poll task state and final evaluations. |
| `GET /api/v1/tasks/{task_id}/variants/{image_id}` | Download a final variant. |
| `GET /health` | Confirm the process is running. |

Task submission returns `202 Accepted`; the client polls until the task is
`completed` or `failed`.

## Behavior worth knowing

- PNG and JPEG inputs only; JSON filenames must exactly match uploaded files.
- One evaluator request checks every recommendation and brand criterion for a
  variant.
- Independent image pipelines run concurrently within a fixed per-task bound.
- Repairs always start from the original creative, preventing visual drift.
- `overall_pass` is derived from validated individual checks, not trusted as a
  model-provided summary.
- Task IDs, image IDs, and artifact paths are server-owned.

## Configuration

- `.env` or the deployment environment supplies the secret `OPENAI_API_KEY`.
- `APP_CONFIG_FILE` selects one complete non-secret TOML document.
- [`config/dev.toml`](config/dev.toml) and
  [`config/test.toml`](config/test.toml) are the authoritative examples for
  provider, timeout, limit, logging, and storage values.
- Runtime values intentionally live in TOML rather than being duplicated here.

## Verify

```shell
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

- Default tests are deterministic and never call OpenAI.
- The real-provider smoke test requires `RUN_OPENAI_SMOKE_TEST=1` and a key.

## Container checks

- The Docker image installs from `uv.lock`, runs as a non-root user, and starts
  one Uvicorn worker.
- CI runs Python checks, then builds the image and probes its user, `/health`,
  and `/docs`.

## What this does not try to solve

- Process-local task state and local artifacts; a restart cannot resume tasks.
- No authentication, tenant isolation, durable queue, database, or object
  storage.
- Model evaluations are useful judgements, not pixel-perfect proof of brand
  compliance.
- No automatic provider retries or partial-success task responses.

For the workflow diagram and trade-offs, see [DESIGN.md](DESIGN.md).
