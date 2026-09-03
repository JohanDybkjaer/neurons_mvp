.PHONY: check-api-key dev docker-build docker-run

PORT ?= 8000
DOCKER_IMAGE ?= visual-recommendations-mvp
DOCKER_PORT ?= 8000
DOCKER_CONFIG ?= config/dev.toml
ENV_FILE ?= .env

## Create the ignored secret file once and require a real key before startup.
check-api-key:
	@if [ ! -f "$(ENV_FILE)" ]; then \
		cp .env.example "$(ENV_FILE)"; \
		echo "Created $(ENV_FILE). Set OPENAI_API_KEY, then run this command again."; \
		exit 1; \
	fi
	@if ! grep -Eq '^OPENAI_API_KEY=.+$$' "$(ENV_FILE)" || \
		grep -Fxq 'OPENAI_API_KEY=your_api_key_here' "$(ENV_FILE)"; then \
		echo "Set a non-placeholder OPENAI_API_KEY in $(ENV_FILE)."; \
		exit 1; \
	fi

## Start the API with the committed development configuration.
dev: check-api-key
	APP_CONFIG_FILE=config/dev.toml uv run uvicorn app.main:app --app-dir src --port $(PORT)

## Build the application image from the committed lockfile.
docker-build:
	docker build --tag $(DOCKER_IMAGE) .

## Run the image with the local secret file and a committed configuration document.
docker-run: check-api-key
	docker run --rm --publish $(DOCKER_PORT):8000 \
		--env-file $(ENV_FILE) \
		--env APP_CONFIG_FILE=$(DOCKER_CONFIG) \
		$(DOCKER_IMAGE)
