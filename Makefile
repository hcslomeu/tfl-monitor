.PHONY: help bootstrap api check openapi-ts

help:
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install Python + Node deps; create .env
	@uv --version >/dev/null 2>&1 || { echo "uv not installed. See https://docs.astral.sh/uv/"; exit 1; }
	@pnpm --version >/dev/null 2>&1 || { echo "pnpm not installed. See https://pnpm.io/"; exit 1; }
	uv sync
	pnpm --dir web install
	@test -f .env || cp .env.example .env
	@echo "Bootstrap complete. Edit .env and run 'make api'."

api: ## Run the API locally with .env loaded (http://localhost:8000)
	uv run task api-debug

check: ## Lint + Python tests + TS lint + TS test + TS build
	uv run task lint
	uv run task test
	pnpm --dir web lint
	pnpm --dir web test
	pnpm --dir web build

openapi-ts: ## Regenerate TS types from OpenAPI
	pnpm --dir web exec openapi-typescript ../contracts/openapi.yaml -o lib/types.ts
