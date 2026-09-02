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

Select exactly one configuration document through `APP_CONFIG_FILE`:

```shell
APP_CONFIG_FILE=config/dev.toml uv run uvicorn app.main:app
```

Use `config/test.toml` for a deployed test instance. `APP_CONFIG_FILE` is
intentionally not placed in `.env`, keeping that file limited to secrets.
