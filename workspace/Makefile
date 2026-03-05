# OpenClaw Researcher — Makefile
# Common operations for development and deployment

WORKSPACE := $(HOME)/.openclaw/workspace
CONDA_ENV := openclaw_researcher
PYTHON := conda run -n $(CONDA_ENV) python

.PHONY: help setup deploy verify clean mlflow-ui

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup:  ## Create conda env and install dependencies
	conda create -n $(CONDA_ENV) python=3.11 -y
	conda run -n $(CONDA_ENV) pip install -r scripts/requirements.txt

verify:  ## Verify all scripts run with --help
	@echo "=== Verifying scripts ==="
	@for script in scripts/*.py; do \
		echo "  $$script ..."; \
		$(PYTHON) $$script --help > /dev/null 2>&1 && echo "  OK" || echo "  FAIL"; \
	done
	@echo "=== Verifying config ==="
	@python3 -c "import json; json.load(open('openclaw.json'))" && echo "  openclaw.json OK"
	@echo "=== Done ==="

deploy:  ## Deploy workspace to ~/.openclaw/workspace/
	@echo "Deploying to $(WORKSPACE)..."
	@mkdir -p $(WORKSPACE)
	@rsync -av --exclude='__pycache__' --exclude='.git' \
		--exclude='*.example.json' --exclude='*.example.yaml' \
		./ $(WORKSPACE)/
	@echo "Deployed. Ensure .env is configured at $(WORKSPACE)/.env"

clean:  ## Remove generated artifacts (state, data, experiments, reports)
	rm -rf state/*.json state/*.md state/*.yaml
	rm -rf data/chroma/ data/mlflow/
	rm -rf experiments/iter_*/
	rm -rf reports/*.md
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned all generated artifacts"

mlflow-ui:  ## Launch MLflow UI on port 5000
	$(PYTHON) -m mlflow ui --backend-store-uri $(WORKSPACE)/data/mlflow --port 5000
