# neurons_mvp

Minimal viable, maintainable solution to the visual-recommendations case.

## Local configuration

Copy `.env.example` to `.env`, replace the API-key placeholder, and keep that
local file uncommitted:

```shell
cp .env.example .env
```

The ignored `.env` file contains secrets only. The application also accepts
`OPENAI_API_KEY` directly from the shell or container environment, which takes
precedence over `.env`.

All non-secret settings—including model selection and logging level—are in
complete root-level `config/dev.toml` and `config/test.toml` files. The Python
`src/app/config/` package only loads and validates the selected file; it does
not define another set of defaults.

Each TOML groups the active settings under `providers`, `limits`, `logging`,
and `storage` sections. `limits.max_iterations` is required and accepts an
integer from 1 through 5. It controls the maximum generation-and-evaluation
iterations for each image; the initial generation counts as iteration 1. The
application still enforces five as a hard code limit.

Select exactly one configuration document through `APP_CONFIG_FILE`:

```shell
APP_CONFIG_FILE=config/dev.toml uv run uvicorn app.main:app --app-dir src
```

For a deployed test instance:

```shell
APP_CONFIG_FILE=config/test.toml uv run uvicorn app.main:app --app-dir src
```

`APP_CONFIG_FILE` is intentionally not placed in `.env`, keeping that file
limited to secrets.

## Code map

- `api/` validates HTTP input and exposes health and task routes.
- `schema_models/` owns Pydantic schemas for inputs, evaluations, and tasks.
- `workflows/` coordinates up to ten image pipelines, with two active at a
  time, and bounded generation/evaluation iterations per image.
- `ai_services/` contains provider adapters; `openai.py` owns OpenAI payloads.
- `config/` selects, loads, and validates configuration once at startup.
- `main.py` composes the application and owns long-lived process state.

The main request path is: API validation → workflow orchestration → AI service
adapter → validated evaluation → task result. Provider payloads do not enter the
workflow directly.

With the server running, open `http://127.0.0.1:8000/docs` for the interactive
Swagger UI.

## Demo

The unchanged assignment inputs are committed under `examples/demo/`. In
Swagger, open `POST /api/v1/demo/tasks`, click **Try it out**, and execute the
request without selecting files. The demo endpoint supplies both creatives and
the matching JSON documents automatically.

Each form field remains optional and editable: selecting images,
recommendations, or brand guidelines replaces that bundled default. The normal
`POST /api/v1/tasks` endpoint continues to require all uploads.

The endpoint uses the configured AI provider and may incur API costs;
automated tests use a fake service instead.

## Real API smoke test

The opt-in smoke test creates one small local creative, generates one variant,
and evaluates it. It does not inspect the generated image visually. With a real
API key available through the shell or ignored `.env` file, run:

```shell
APP_CONFIG_FILE=config/dev.toml RUN_OPENAI_SMOKE_TEST=1 uv run pytest -m real_api
```

The test makes paid provider calls. It is skipped unless
`RUN_OPENAI_SMOKE_TEST=1` is set.
