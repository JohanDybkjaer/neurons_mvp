# Visual Recommendations - Minimal Viable Solution Plan

`DESIGN.md` is the source of truth for scope and architecture. This plan
delivers that design in three reviewable branches. It uses proportionate best
practices while intentionally avoiding a branch per layer, speculative
abstractions, or unnecessary infrastructure.

## Branch workflow

- Start each branch from the latest merged `main`.
- Implement only the work listed for that branch.
- Keep implementation, tests, and directly affected documentation together.
- Merge a branch only after its checks pass.
- Update `DESIGN.md` before implementing a materially different design.
- Keep dependency and tool configuration in `pyproject.toml` and commit every
  intentional `uv.lock` change.
- Once a quality tool is introduced, run it on every subsequent branch; do not
  postpone new violations to the final step.

## Progress

- [x] Step 1 - `mvp/api-and-workflow`
- [ ] Step 2 - `mvp/openai-integration`
- [ ] Step 3 - `mvp/container-and-demo`

## Step 1 - `mvp/api-and-workflow`

### Purpose

Build a complete deterministic vertical slice before introducing paid,
nondeterministic model calls.

### Deliverables

- Create the minimal Python project with FastAPI, Pydantic, Pillow, Uvicorn,
  python-multipart, pytest, and HTTP test dependencies managed by `uv`.
- Keep application code to the concerns described in `DESIGN.md` unless
  a concrete implementation need proves otherwise.
- Define a small configuration package with validated settings for the runtime
  root, image upload limit, and provider timeout.
- Use `create_app` as the composition root and inject configuration and the
  image service directly, without a dependency-injection framework.
- Keep task routes together under `app/api/v1/` with the `/api/v1` prefix, keep
  `/health` unversioned, and register both routers in `main.py`.
- Keep FastAPI types at the HTTP boundary and provider-specific details out of
  the workflow.
- Define the recommendation, brand-guideline, task, result, and structured
  evaluation models.
- Implement:
  - `POST /api/v1/tasks`
  - `GET /api/v1/tasks/{task_id}`
  - `GET /api/v1/tasks/{task_id}/variants/{image_id}`
  - `GET /health`
- Accept one or two image files plus the two supplied JSON-file shapes through
  `multipart/form-data`.
- Perform only the boundary validation required by the design.
- Store task state in memory and files under a task-specific runtime directory.
- Run the image pipelines concurrently with a maximum concurrency of two.
- Keep generation, evaluation, and the optional single repair sequential within
  each image pipeline.
- Evaluate every recommendation and brand criterion in one call per generated
  variant.
- Use a deterministic fake service in tests. It may copy the source image as its
  generated output and return configured evaluation results.
- Mark a technically completed workflow as `completed` even when its final
  evaluation has `overall_pass: false`. Reserve `failed` for execution errors.

### Checks

- Swagger/OpenAPI exposes the complete multipart and polling contract.
- A valid two-image request returns `202` immediately and later completes with
  two retrievable variants and evaluations.
- Both image pipelines can be in flight at the same time.
- The evaluator receives all recommendations for its image in one invocation.
- A failed first evaluation causes exactly one repair and one re-evaluation.
- A failed second evaluation becomes the final result and cannot loop again.
- Invalid JSON, invalid images, and mismatched filenames are rejected safely.
- Provider exceptions produce a safe failed-task response.
- The test suite runs without network access or credentials.
- Configuration tests inject immutable settings directly; application code does
  not read environment variables outside the configuration package.

## Step 2 - `mvp/openai-integration`

### Purpose

Replace the deterministic test behavior with the two real AI roles while
preserving the already-tested workflow.

### Deliverables

- Implement one asynchronous `OpenAIService` with two focused methods:
  - Edit an original creative from its recommendations and brand guidelines.
  - Evaluate the original and variant using a schema-constrained vision
    response.
- Extend the configuration package to load and validate only `OPENAI_API_KEY`,
  `IMAGE_MODEL`, and `EVALUATION_MODEL`; keep environment reads out of route,
  workflow, and provider methods.
- Construct one asynchronous OpenAI client for the application and close it via
  the FastAPI lifespan.
- Build a direct editing prompt without adding a planning stage.
- Make brand guidelines authoritative in initial and repair prompts.
- Send all recommendations and brand criteria in a single evaluator request.
- Validate evaluator output with the Pydantic evaluation model before the
  workflow uses it.
- Build the one repair prompt from the validated failed checks and always repair
  from the original creative.
- Keep the deterministic fake injected by automated tests; do not add a general
  provider framework.
- Add mocked adapter tests for successful generation, successful evaluation,
  malformed evaluator output, and a provider exception.
- Add one explicitly enabled real-API smoke test for a single creative.

### Checks

- Default tests remain deterministic and network-free.
- Model output cannot enter application control flow without schema validation.
- One successful image pipeline makes one image-editing call and one evaluator
  call.
- One failed first evaluation adds no more than one call of each kind.
- The real smoke test is skipped unless explicitly enabled and credentials are
  present.
- Invalid or missing required configuration fails at startup without exposing a
  secret, and tests can still supply settings without environment mutation.
- Application shutdown closes the OpenAI client.

## Step 3 - `mvp/container-and-demo`

### Purpose

Make the small service easy to run, inspect, and discuss in the interview.

### Deliverables

- Add a Dockerfile based on a small pinned Python image that installs from
  `uv.lock`, runs as a non-root user, and starts one Uvicorn worker.
- Add `.dockerignore`, `.gitignore`, and `.env.example` entries needed by the
  MVP.
- Configure Ruff formatting/linting and mypy for application code in
  `pyproject.toml`; keep the rule set small and document any necessary exclusion.
- Add one minimal CI workflow that performs a frozen dependency install and
  runs Ruff, mypy, and the default pytest suite.
- Include the supplied creatives and JSON files unchanged as demo inputs.
- Add standard-library logging for task ID, image ID, step, attempt, duration,
  and outcome without logging sensitive payloads.
- Write a concise README covering:
  - Local setup with `uv`.
  - Docker build and run commands.
  - Required environment variables.
  - The Swagger UI demonstration flow.
  - The asynchronous submit-and-poll behavior.
  - Accepted limitations from `DESIGN.md`.
- Run the full automated test suite.
- Manually verify the supplied two-image request through Swagger UI.
- If credentials and budget are available, run the opt-in smoke test once and
  record only the outcome, not generated assets or secrets.

### Checks

- The image builds and starts successfully with one worker.
- `/health` and `/docs` are reachable in the container.
- The supplied files can be selected directly in Swagger UI.
- A submitted task returns immediately and can be polled to a terminal state.
- Successful variants can be downloaded from their returned URLs.
- Ruff formatting and linting, mypy, and the default pytest suite pass locally
  and in CI.
- The container process is non-root and starts from the committed lockfile.

## Completion

The MVP is finished after Step 3 when every acceptance criterion in
`DESIGN.md` is satisfied. Do not add a production-hardening branch unless a
new requirement explicitly changes the scope.
