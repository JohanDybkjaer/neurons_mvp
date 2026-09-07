.PHONY: check-api-key dev docker-build docker-run docker-run-docs

PORT ?= 8000
DOCKER_IMAGE ?= visual-recommendations-mvp
DOCKER_CONTAINER ?= visual-recommendations-mvp-api
DOCKER_PORT ?= 8000
DOCKER_CONFIG ?= config/dev.toml
RUNTIME_VOLUME ?= visual-recommendations-mvp-runtime
ENV_FILE ?= .env
DOCKER_DOCS_URL ?= http://127.0.0.1:$(DOCKER_PORT)/docs
BROWSER_OPEN ?= open

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
	docker run --rm --name $(DOCKER_CONTAINER) --publish $(DOCKER_PORT):8000 \
		--env-file $(ENV_FILE) \
		--env APP_CONFIG_FILE=$(DOCKER_CONFIG) \
		--mount type=volume,source=$(RUNTIME_VOLUME),target=/app/runtime \
		$(DOCKER_IMAGE)

## Start the API in the background and open Swagger UI once it is ready (macOS).
docker-run-docs: check-api-key
	docker run --detach --rm --name $(DOCKER_CONTAINER) --publish $(DOCKER_PORT):8000 \
		--env-file $(ENV_FILE) \
		--env APP_CONFIG_FILE=$(DOCKER_CONFIG) \
		--mount type=volume,source=$(RUNTIME_VOLUME),target=/app/runtime \
		$(DOCKER_IMAGE)
	@attempts=0; until curl --fail --silent --output /dev/null http://127.0.0.1:$(DOCKER_PORT)/health; do \
		attempts=$$((attempts + 1)); \
		if [ $$attempts -ge 30 ]; then \
			echo "API did not become healthy within 30 seconds. Check: docker logs $(DOCKER_CONTAINER)"; \
			exit 1; \
		fi; \
		sleep 1; \
	done
	$(BROWSER_OPEN) $(DOCKER_DOCS_URL)
