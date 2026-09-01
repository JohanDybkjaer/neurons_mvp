# Engineering Instructions - Minimal MVP

## Source of truth

- Read `DESIGN.md`, `PLAN.md`, the relevant code, and the relevant tests
  before changing behavior.
- Treat `DESIGN.md` as the architecture and scope contract.
- Follow the current branch step in `PLAN.md`; do not implement later steps
  early.
- If implementation needs a materially different design, update the design and
  plan explicitly rather than silently expanding the architecture.

## Simplicity is a requirement

- Make the smallest coherent change that completes the current branch step.
- Prefer direct functions, Pydantic models, and explicit data flow over generic
  frameworks or speculative abstractions.
- Keep the application near the module structure in `DESIGN.md`.
- Do not add a database, migrations, Redis, a distributed queue, multiple
  workers, object storage, authentication, a custom frontend, an agent
  framework, or a planning agent.
- Do not add generalized repositories, service layers, factories, registries,
  plugin systems, exception hierarchies, or configuration systems for possible
  future needs.
- Do not implement production hardening that is listed as a non-goal.
- Preserve unrelated user changes and avoid unrelated refactoring.

These exclusions are intentional MVP decisions. Add one only after an explicit
requirement changes and the design is updated.

## Required architecture

- Run one FastAPI process with one Uvicorn worker.
- Keep task state in a process-local dictionary.
- Store input and generated images under server-generated task directories.
- Use one small `OpenAIService` for image editing and visual evaluation.
- Inject a deterministic fake service in automated tests; do not build a general
  multi-provider abstraction.
- Use Pydantic models at HTTP, JSON-file, and model-output boundaries.
- Never use unvalidated model prose to control application behavior.

## Workflow invariants

- Accept no more than two images per task.
- Process the two image pipelines concurrently with a hard limit of two.
- Within an image pipeline, run generation, evaluation, optional repair, and
  re-evaluation sequentially.
- Send all recommendations and brand criteria for one variant in one evaluator
  request. Do not make a model call per recommendation.
- Generate one initial variant per creative.
- If the initial evaluation fails, allow exactly one repair attempt.
- Always generate and repair from the original creative, never from a previous
  generated attempt.
- After re-evaluation, store that result whether it passes or fails. Do not loop.
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
- Add comments only for non-obvious constraints or decisions. Do not narrate
  straightforward code.
- Add docstrings only where a public contract or non-obvious side effect needs
  explanation.
- Remove temporary code, dead code, and stale comments before completing a
  branch.

## Testing

- Add or update tests for every observable behavior change.
- Keep the default suite deterministic, fast, credential-free, and independent
  of network access.
- Test public behavior and workflow outcomes rather than private implementation
  details.
- Cover the normal two-image workflow, bounded concurrency, combined evaluation,
  the single repair limit, invalid boundary input, and a technical provider
  failure.
- Keep real OpenAI testing explicit and opt-in. Never run it as part of the
  default suite.
- Do not weaken or remove a test to make an implementation pass.
- Run focused tests while developing and the full suite before branch handoff.

## Dependencies and configuration

- Manage Python dependencies with `uv` and keep `uv.lock` synchronized.
- Add a dependency only when the current branch cannot be implemented clearly
  with the standard library or an already required package.
- Keep runtime configuration limited to `OPENAI_API_KEY`, `IMAGE_MODEL`, and
  `EVALUATION_MODEL` unless a new requirement is documented first.
- Use Python's standard `logging` module; do not add a logging framework.
- Run exactly one Uvicorn worker because task state is in memory.

## Branch delivery

- Use the exact branch names and ordering in `PLAN.md` unless the user asks
  for a change.
- Before handoff, run the checks listed for the current branch.
- Report what changed, which checks ran, and any remaining limitation or risk.
- Mark a plan step complete only when its deliverables and checks are genuinely
  complete.
- Stop when the acceptance criteria are met. Do not create extra polish or
  hardening work merely because it could be useful later.
