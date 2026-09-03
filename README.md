# Visual Recommendations MVP

Async FastAPI service for generating and evaluating improved marketing creatives
from structured recommendations and brand guidelines.

## Review in two minutes

- **Try it:** Start the service, open Swagger UI, and submit the supplied sample
  files to `POST /api/v1/tasks`.
- **Workflow:** Generate from the original → evaluate all checks → repair only
  when required → return the final variant.
- **Engineering:** Async task API, bounded concurrency, validated boundaries,
  deterministic tests, Docker, and CI.
- **Scope:** A deliberately small technical-interview case, not a claim of
  horizontally scalable production infrastructure.

## Run with sample inputs

```shell
uv sync
cp .env.example .env
# Set OPENAI_API_KEY in .env.
make dev
```

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

## Key properties

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

## Docker

```shell
make docker-build
make docker-run
```

- Installs from `uv.lock`.
- Runs as a non-root user with one Uvicorn worker.
- CI runs Python checks, then builds the image and probes its user, `/health`,
  and `/docs`.

## Deliberate MVP boundaries

- Process-local task state and local artifacts; a restart cannot resume tasks.
- No authentication, tenant isolation, durable queue, database, or object
  storage.
- Model evaluations are useful judgements, not pixel-perfect proof of brand
  compliance.
- No automatic provider retries or partial-success task responses.

For the design rationale and workflow diagram, see [DESIGN.md](DESIGN.md).
