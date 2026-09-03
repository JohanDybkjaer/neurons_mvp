# Visual Recommendations MVP

A small FastAPI service that edits marketing creatives from structured
recommendations, evaluates each generated variant against brand guidelines, and
returns a retrievable final image with a structured evaluation.

The service is deliberately bounded: a request accepts up to ten images, runs
at most two image pipelines at once, and permits no more than five
generation-and-evaluation iterations per image. See [DESIGN.md](DESIGN.md) for
the architecture and deliberate MVP limitations.

## What you can do

- Submit one to ten PNG or JPEG creatives with matching recommendation and
  brand-guideline JSON files.
- Poll a task while it runs, then retrieve each final generated variant.
- Use the bundled two-image demo without preparing uploads.
- Set `max_iterations` from 1 through 5 to control the per-image repair limit.

The server starts without calling OpenAI. A demo or task submission uses the
configured provider models and can incur API costs.

## Requirements

- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/)
- An OpenAI API key only when submitting a task or running the real-API smoke
  test

## Quick start

Install the locked project dependencies:

```shell
# Create the project environment from uv.lock.
uv sync
```

Create the local secret file:

```shell
# Copy the safe API-key placeholder into an ignored local file.
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env` when you are ready to make paid provider calls:

```dotenv
# .env contains secrets only and must remain uncommitted.
OPENAI_API_KEY=your_api_key_here
```

Start the development configuration:

```shell
# Select the committed development configuration and start one Uvicorn worker.
make dev
```

The launcher defaults to port 8001. To use another local port:

```shell
make dev PORT=8002
```

Application logs continue to appear in the terminal and are also written to
`runtime/logs/app.log`. Starting the API clears prior runtime logs, so this
file contains only the current run. Task artifacts remain under
`runtime/tasks/` for manual inspection. The `runtime/` directory is ignored by
Git.

Check that the process is running:

```shell
# The health endpoint never calls the provider.
curl http://127.0.0.1:8001/health
```

Expected response:

```json
{
  "status": "ok"
}
```

Open [Swagger UI](http://127.0.0.1:8001/docs) to submit and inspect requests
interactively. The route descriptions, field descriptions, response examples,
and response schemas are generated from FastAPI and Pydantic metadata.

## Run a task

### Try the bundled demo

The demo endpoint uses the committed images and JSON documents in
[`examples/demo/`](examples/demo/) when no files are supplied. It follows the
same validation, workflow, limits, and provider configuration as a normal task.

Submit the bundled demo only when you are ready for paid calls:

```shell
# Submit the two bundled creatives and receive a polling URL.
curl -X POST http://127.0.0.1:8001/api/v1/demo/tasks
```

The response is returned immediately while processing continues:

```json
{
  "task_id": "7f2b4f9d-6c65-4b38-8e73-487750d0c478",
  "status": "pending",
  "status_url": "/api/v1/demo/tasks/7f2b4f9d-6c65-4b38-8e73-487750d0c478"
}
```

Poll the `status_url` from the response until the status becomes `completed` or
`failed`:

```shell
# Replace <task_id> with the task ID returned by the POST response.
curl http://127.0.0.1:8001/api/v1/demo/tasks/<task_id>
```

A completed task returns one result per image. `attempts` is the number of
generation-and-evaluation pairs that actually ran, while `overall_pass` is the
final evaluation outcome:

```json
{
  "task_id": "7f2b4f9d-6c65-4b38-8e73-487750d0c478",
  "status": "completed",
  "results": [
    {
      "image_id": "image_1",
      "source_filename": "creative_1.png",
      "variant_url": "/api/v1/demo/tasks/<task_id>/variants/image_1",
      "attempts": 1,
      "evaluation": {
        "recommendations": [
          {
            "id": "rec_1",
            "applied": true,
            "reason": "The requested visual change is visible."
          }
        ],
        "brand_checks": [
          {
            "criterion": "Keep the logo",
            "compliant": true,
            "reason": "The logo remains visible."
          }
        ],
        "overall_pass": true
      }
    }
  ],
  "error": null
}
```

Download an image only after its task is complete:

```shell
# Replace <task_id> and <image_id> with values from a completed task result.
curl --output variant.png \
  http://127.0.0.1:8001/api/v1/demo/tasks/<task_id>/variants/<image_id>
```

### Submit your own creatives

`POST /api/v1/tasks` requires three multipart fields:

| Field | Required value |
| --- | --- |
| `images` | One to ten PNG or JPEG files, submitted once per image. |
| `recommendations` | One JSON file with recommendations for every filename. |
| `brand_guidelines` | One JSON file with guidelines for every filename. |

The outer keys of the JSON files are arbitrary labels. The `filename` inside
each entry is the join key and must exactly match an uploaded image filename.
The complete two-image files are available as
[recommendations.json](examples/demo/recommendations.json) and
[brand_guidelines.json](examples/demo/brand_guidelines.json).

This is the required shape for one entry in `recommendations.json`:

```json
{
  "image1": {
    "filename": "creative_1.png",
    "recommendations": [
      {
        "id": "rec_1",
        "title": "Add a focal accent",
        "description": "Add a small red circle below the headline.",
        "type": "composition"
      }
    ]
  }
}
```

The matching `brand_guidelines.json` entry has the same filename:

```json
{
  "image1": {
    "filename": "creative_1.png",
    "brand_guidelines": {
      "protected_regions": ["Keep the logo"],
      "typography": "Maintain the existing typography.",
      "aspect_ratio": "Maintain the original aspect ratio.",
      "brand_elements": "Keep brand elements visible."
    }
  }
}
```

Submit the committed two-image example through the product endpoint:

```shell
# Submit both creatives and the JSON documents that reference their filenames.
curl -X POST http://127.0.0.1:8001/api/v1/tasks \
  -F "images=@examples/demo/creative_1.png;type=image/png" \
  -F "images=@examples/demo/creative_2.png;type=image/png" \
  -F "recommendations=@examples/demo/recommendations.json;type=application/json" \
  -F "brand_guidelines=@examples/demo/brand_guidelines.json;type=application/json"
```

Use the returned `status_url` exactly as in the demo flow. The product endpoint
uses `/api/v1/tasks/<task_id>` instead of `/api/v1/demo/tasks/<task_id>`.

## Configuration and limits

Choose exactly one complete TOML document with `APP_CONFIG_FILE`. `.env` is
secret-only: `OPENAI_API_KEY` from the shell or container environment takes
precedence over `.env`, while every non-secret setting comes from the selected
TOML file.

| Setting | Development value | Meaning |
| --- | --- | --- |
| `providers.image_editor_model` | `gpt-image-2` | Model used to edit creatives. |
| `providers.evaluator_model` | `gpt-5.6-terra` | Model used to evaluate variants. |
| `providers.timeout_seconds` | `120` | Timeout applied to each provider operation. |
| `limits.max_image_size_mb` | `10` | Maximum accepted upload size per image. |
| `limits.max_iterations` | `2` | Maximum generation/evaluation pairs for each image. |
| `logging.level` | `DEBUG` | Application log threshold. |
| `storage.artifact_root` | `runtime/tasks` | Server-managed task input and variant directory. |

The initial generation and evaluation count as iteration 1. Set
`max_iterations = 1` to disable repairs. The configuration accepts values from
1 through 5, and the workflow enforces five as a hard cap even for direct calls.

When an evaluation fails and an iteration remains, the next generation uses the
original creative and only the latest failed checks as feedback. It does not
edit a previous generated variant, which avoids cumulative drift.

| Fixed workflow limit | Value |
| --- | --- |
| Images per request | 1–10 |
| Active image pipelines per task | 2 |
| Maximum iterations per image | 5 |

At most two image pipelines are active per task. Within one pipeline,
generation and evaluation are sequential. A visual failure at the configured
limit still produces a `completed` task with `overall_pass: false`; `failed` is
reserved for technical execution errors.

## Test safely before a real request

Run the default credential-free suite:

```shell
# Run deterministic tests with the fake AI service.
uv run pytest
```

Run the opt-in real-API smoke test only when you are ready for a small paid
request. It creates one local creative, generates one variant, and evaluates it
without visually inspecting the generated image:

```shell
# Opt into one paid image edit and one paid evaluation.
APP_CONFIG_FILE=config/dev.toml RUN_OPENAI_SMOKE_TEST=1 uv run pytest -m real_api
```

## Project map

| Path | Responsibility |
| --- | --- |
| `src/app/main.py` | Application composition, lifespan, and process-local state. |
| `src/app/api/` | HTTP routes, upload validation, task polling, and artifacts. |
| `src/app/config/` | TOML selection, secret loading, and typed validation. |
| `src/app/schema_models/` | Pydantic input, evaluation, task, and OpenAPI schemas. |
| `src/app/workflows/` | Bounded generation, evaluation, repair, and concurrency. |
| `src/app/ai_services/openai.py` | OpenAI image-edit and visual-evaluation requests. |
| `examples/demo/` | Committed demo images and matching JSON documents. |

The service runs as one Uvicorn worker with process-local task state. Restarting
the process clears task status and runtime logs; prior task artifacts remain on
disk but cannot be retrieved through the restarted API. This is an intentional
MVP limitation documented in [DESIGN.md](DESIGN.md).
