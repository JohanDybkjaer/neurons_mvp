.PHONY: dev docker-build docker-run

PORT ?= 8000
DOCKER_IMAGE ?= visual-recommendations-mvp
DOCKER_PORT ?= 8000
DOCKER_CONFIG ?= config/dev.toml

## Start the API with the committed development configuration.
dev:
	APP_CONFIG_FILE=config/dev.toml uv run uvicorn app.main:app --app-dir src --port $(PORT)

## Build the application image from the committed lockfile.
docker-build:
	docker build --tag $(DOCKER_IMAGE) .

## Run the image with the local secret file and a committed configuration document.
docker-run:
	docker run --rm --publish $(DOCKER_PORT):8000 \
		--env-file .env \
		--env APP_CONFIG_FILE=$(DOCKER_CONFIG) \
		$(DOCKER_IMAGE)
