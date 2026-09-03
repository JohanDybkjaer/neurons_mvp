# Engineering Instructions - Minimal Viable Solution

## Source of truth

- Read `DESIGN.md`, `PLAN.md`, the relevant code, and the relevant tests
  before changing behavior.
- Treat `DESIGN.md` as the architecture and scope contract.
- Follow the current branch step in `PLAN.md`; do not implement later steps
  early.
- If implementation needs a materially different design, update the design and
  plan explicitly rather than silently expanding the architecture.

## Simplicity and maintainability are requirements

- Make the smallest coherent, maintainable change that completes the current
  branch step.
- Prefer direct functions, Pydantic models, and explicit data flow over generic
  frameworks or speculative abstractions.
- Keep the application near the module structure in `DESIGN.md`.
- Use a small package when it gives an active concern clear ownership, but do
  not add layers or files only for architectural symmetry.
- Do not add a database, migrations, Redis, a distributed queue, multiple
  workers, object storage, authentication, a custom frontend, an agent
  framework, or a planning agent.
- Do not add generalized repositories, service layers, factories, registries,
  plugin systems, exception hierarchies, or configuration frameworks for
  possible future needs.
- Do not implement production hardening that is listed as a non-goal.
- Preserve unrelated user changes and avoid unrelated refactoring.

These exclusions are intentional minimal-solution decisions. Add one only after
an explicit requirement changes and the design is updated.

## Required architecture

- Run one FastAPI process with one Uvicorn worker.
- Keep task state in a process-local dictionary.
- Store input and generated images under server-generated task directories.
- Use one small `OpenAIService` for image editing and visual evaluation.
- Inject a deterministic fake service in automated tests; do not build a general
  multi-provider abstraction.
- Use Pydantic models at HTTP, JSON-file, and model-output boundaries.
- Never use unvalidated model prose to control application behavior.

## Project organization and dependency flow

- Treat `create_app` as the composition root. Construct application-owned state
  and long-lived clients there, inject narrow dependencies explicitly, and do
  not introduce a dependency-injection container.
- Keep all environment access and settings validation in `app/config/`. Export
  the small public settings interface from `config/__init__.py`; other modules
  must not call `os.getenv` or depend on configuration internals.
- Keep product routes in `app/api/v1/` under the `/api/v1` URL prefix. Keep
  `/health` unversioned, and keep `main.py` limited to application construction,
  state ownership, and router registration.
- Keep dependencies one-way: HTTP layer to workflow, workflow to validated
  models and the image-service contract, and the OpenAI adapter to provider
  APIs. `workflow.py` must remain independent of FastAPI and provider payloads.
- Use one module for one cohesive concern. The `api/` and `config/` packages own
  explicit boundaries; do not add further one-file packages, one-class modules,
  or placeholder directories for possible growth.
- Create expensive or connection-owning clients once per application and close
  them through the FastAPI lifespan. Do not create an OpenAI client per call.
- Keep module imports free of filesystem creation, network calls, and other
  hidden side effects; perform startup work explicitly in the composition root.

## Workflow invariants

- Accept one through ten images per task.
- Process image pipelines concurrently with a hard limit of two.
- Within an image pipeline, run generation, evaluation, and optional repairs
  sequentially.
- Send all recommendations and brand criteria for one variant in one evaluator
  request. Do not make a model call per recommendation.
- Generate one initial variant per creative.
- If evaluation fails, allow repairs only until the configured iteration limit,
  with a hard ceiling of five iterations including the initial attempt.
- Always generate and repair from the original creative, never from a previous
  generated attempt.
- After every evaluation, store the final result whether it passes or fails. Do
  not exceed the configured iteration bound.
- Use `completed` when the workflow ran to completion, even if
  `overall_pass` is false. Use `failed` only for technical execution failures.

## Validation and safety

- Treat uploads, JSON, environment values, provider responses, and filenames as
  untrusted at their boundaries.
- Apply only the inexpensive validation required by `DESIGN.md`: image
  count, size, decoded PNG/JPEG format, valid JSON schemas, and filename
  matching.
- Use UUIDs and server-owned identifiers for paths and public artifact lookup.
  Never use an uploaded filename as a filesystem path.
- Return short, safe errors without filesystem paths, provider payloads, or
  secrets.
- Never log API keys, image bytes, complete prompts, or uploaded JSON payloads.
- Bound external calls with a timeout and concurrency limit. Do not add automatic
  retry policies; the one repair is a workflow decision, not a provider retry.
- Use asynchronous provider calls and do not block the event loop with file or
  network work that has an available asynchronous alternative.

## Code quality

- Use descriptive names, type hints, and small focused functions.
- Keep FastAPI handlers thin: parse the request, create or read task state, and
  delegate workflow work.
- Keep OpenAI-specific request construction and response parsing in
  `openai_service.py`.
- Keep orchestration and the bounded repair loop in `workflow.py`.
- Avoid duplicated prompt construction and validation logic.
- Give each application module a concise docstring stating its responsibility.
- Add concise docstrings to public classes and functions, including FastAPI
  handlers so their purpose is visible in Swagger/OpenAPI. Document private
  helpers when their contract, validation rule, or side effect is not obvious.
- Add comments only for non-obvious constraints or decisions. Do not narrate
  straightforward code.
- Keep docstrings and comments current when behavior changes; remove text that
  merely repeats names, types, or straightforward statements.
- Remove temporary code, dead code, and stale comments before completing a
  branch.
- Keep public configuration and service seams small; do not expose internal
  helper functions through package `__init__.py` files.
- Use Ruff for formatting and linting and mypy for application type checking
  once introduced in `PLAN.md`. Keep configuration centralized in
  `pyproject.toml` and prefer fixing findings over broad ignores.

## Testing

- Add or update tests for every observable behavior change.
- Keep the default suite deterministic, fast, credential-free, and independent
  of network access.
- Test public behavior and workflow outcomes rather than private implementation
  details.
- Cover the normal two-image workflow, bounded concurrency, combined evaluation,
  configurable iteration limits, invalid boundary input, and a technical
  provider failure.
- Keep real OpenAI testing explicit and opt-in. Never run it as part of the
  default suite.
- Do not weaken or remove a test to make an implementation pass.
- Run focused tests while developing and the full suite before branch handoff.

## Dependencies and configuration

- Manage Python dependencies with `uv` and keep `uv.lock` synchronized.
- Add a dependency only when the current branch cannot be implemented clearly
  with the standard library or an already required package.
- Keep runtime configuration limited to `OPENAI_API_KEY`, `APP_CONFIG_FILE`,
  and the documented settings in one selected TOML file unless a new
  requirement is documented first.
- Validate settings once at startup, fail fast with a safe message, and pass the
  resulting immutable configuration explicitly. Tests should construct settings
  directly rather than mutate global environment state.
- Document environment names with safe placeholders in `.env.example`; never
  commit `.env` files, credentials, or generated runtime artifacts.
- Use Python's standard `logging` module; do not add a logging framework.
- Run exactly one Uvicorn worker because task state is in memory.

## Branch delivery

- Use the exact branch names and ordering in `PLAN.md` unless the user asks
  for a change.
- Before handoff, run the checks listed for the current branch.
- After the quality tools are introduced, run Ruff formatting/linting, mypy, and
  the default pytest suite before every handoff. CI must run the same commands
  with a frozen lockfile install.
- Report what changed, which checks ran, and any remaining limitation or risk.
- Mark a plan step complete only when its deliverables and checks are genuinely
  complete.
- Stop when the acceptance criteria are met. Do not create extra polish or
  hardening work merely because it could be useful later.
