# Visual Recommendations MVP

Async FastAPI service for generating and evaluating improved marketing creatives
from structured recommendations and brand guidelines.

## Quick overview

- **Try it:** Start the service, open Swagger UI, and submit the supplied sample
  files to `POST /api/v1/tasks`.
- **Workflow:** Generate from the original → evaluate all checks → repair only
  when required → return the final variant.
- **Implementation:** An async task API, deterministic tests, Docker, and CI.
- **Scope:** A small MVP, not a full production platform.

## Run the service

### Docker (recommended)

This packages and runs the entire API: `Docker container → Uvicorn → FastAPI`.
It uses the same image CI builds, and you do not need to install `uv`.

1. Build the image.

   ```shell
   make docker-build
   ```

2. Start the container.

   ```shell
   make docker-run
   ```

3. On the first run, Make creates the ignored `.env` file and stops.
4. Set `OPENAI_API_KEY` in `.env`.
5. Run `make docker-run` again.
6. Open [Swagger UI](http://127.0.0.1:8000/docs).

### Local development with uv

Use this path only when changing or debugging the application.

1. Start the API.

   ```shell
   make dev
   ```

2. On the first run, Make creates `.env` and stops.
3. Set `OPENAI_API_KEY` in `.env`, then run `make dev` again.
4. Open [Swagger UI](http://127.0.0.1:8000/docs).

## Submit the supplied sample inputs

1. In Swagger UI, open `POST /api/v1/tasks` and select **Try it out**.
2. Upload both creatives, `recommendations.json`, and `brand_guidelines.json`
   from [`examples/demo/`](examples/demo/).
3. Select **Execute** and copy the returned `task_id`.
4. Open `GET /api/v1/tasks/{task_id}`, enter the task ID, and execute until the
   status is `completed` or `failed`.
5. When completed, use each result's `variant_url` to download the final image.

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
- `make docker-run` keeps artifacts and logs in the named Docker volume
  `visual-recommendations-mvp-runtime`, mounted at `/app/runtime`.

Inspect that volume after running a task:

```shell
docker run --rm --mount type=volume,source=visual-recommendations-mvp-runtime,target=/app/runtime alpine ls -R /app/runtime
```

## What this does not try to solve

- Process-local task state and local artifacts; a restart cannot resume tasks.
- No authentication, tenant isolation, durable queue, database, or object
  storage.
- Model evaluations are useful judgements, not pixel-perfect proof of brand
  compliance.
- No automatic provider retries or partial-success task responses.

For the workflow diagram and trade-offs, see [DESIGN.md](DESIGN.md).
