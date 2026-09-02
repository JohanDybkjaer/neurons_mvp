.PHONY: dev

PORT ?= 8001

## Start the API with the committed development configuration.
dev:
	APP_CONFIG_FILE=config/dev.toml uv run uvicorn app.main:app --app-dir src --port $(PORT)
