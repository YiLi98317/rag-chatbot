PROJECT_ROOT := $(shell pwd)
VENV := $(PROJECT_ROOT)/.venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
IMAGE ?= rag-api:dev
ENV_FILE ?= .env
SMOKE_BASE_URL ?= http://localhost:8000
COMPOSE := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || (command -v docker-compose >/dev/null 2>&1 && echo "docker-compose" || echo ""))
KIND_CLUSTER ?= rag
K3D_CLUSTER ?= rag
K8S_PROVIDER ?= kind

# Convenience flag: `make chat debug=1` or `make chat DEBUG=1`
DEBUG ?= 0
ifdef debug
DEBUG := $(debug)
endif

.PHONY: venv install ingest ingest-sql query chat smoke reingest-chinook-mysql
.PHONY: up down api
.PHONY: docker-build docker-run compose-up compose-down smoke-compose
.PHONY: k8s-dev-up k8s-dev-down k8s-dev-milvus-up k8s-dev-bootstrap k8s-dev-apply k8s-dev-status k8s-dev-logs
.PHONY: k8s-dev-load-image
.PHONY: dev bootstrap
.PHONY: thucnews-sample-2000 reingest-thucnews-2000 reingest-company-xlsx
.PHONY: clean clean-lite clean-deps clean-docker clean-all

venv:
	@test -d $(VENV) || python3 -m venv $(VENV)

install: venv
	@$(PIP) install --upgrade pip
	@$(PIP) install -r requirements.txt

ingest:
	@PYTHONPATH=$(PROJECT_ROOT)/src $(PY) -m chatbot.cli.ingest --collection $(collection)

ingest-sql:
	@PYTHONPATH=$(PROJECT_ROOT)/src $(PY) -m chatbot.cli.ingest_sql $(args)

query:
	@PYTHONPATH=$(PROJECT_ROOT)/src $(PY) -m chatbot.cli.query "$(q)" --collection "$(collection)" $(args)

chat:
	@PYTHONPATH=$(PROJECT_ROOT)/src $(PY) -m chatbot.cli.chat --collection "$(collection)" $(args) $(if $(filter 1 true TRUE yes YES,$(DEBUG)),--debug,)

smoke:
	@PYTHONPATH=$(PROJECT_ROOT)/src $(PY) scripts/smoke.py

docker-build:
	@docker build -t $(IMAGE) .

docker-run:
	@docker run --rm -p 8000:8000 --env-file $(ENV_FILE) -e PORT=8000 $(IMAGE)

k8s-dev-load-image:
	@if [ "$(K8S_PROVIDER)" = "kind" ]; then \
		if ! command -v kind >/dev/null 2>&1; then \
			echo "ERROR: kind is not installed (needed to load local images)."; \
			echo "Install: brew install kind"; \
			exit 1; \
		fi; \
		echo "Loading $(IMAGE) into kind cluster $(KIND_CLUSTER) ..."; \
		kind load docker-image $(IMAGE) --name $(KIND_CLUSTER); \
	elif [ "$(K8S_PROVIDER)" = "k3d" ]; then \
		if ! command -v k3d >/dev/null 2>&1; then \
			echo "ERROR: k3d is not installed (needed to import local images)."; \
			echo "Install: brew install k3d"; \
			exit 1; \
		fi; \
		echo "Importing $(IMAGE) into k3d cluster $(K3D_CLUSTER) ..."; \
		k3d image import $(IMAGE) -c $(K3D_CLUSTER); \
	else \
		echo "Skipping image load (K8S_PROVIDER=$(K8S_PROVIDER))."; \
		echo "If your cluster can't see local images, set K8S_PROVIDER=kind or k3d."; \
	fi

k8s-dev-milvus-up:
	@if ! command -v helm >/dev/null 2>&1; then \
		echo "ERROR: helm is not installed."; \
		echo "Install: brew install helm"; \
		exit 1; \
	fi
	@helm repo add milvus https://zilliztech.github.io/milvus-helm/ >/dev/null 2>&1 || true
	@helm repo update >/dev/null
	@helm upgrade --install milvus milvus/milvus -f deploy/milvus-values.yaml
	@kubectl rollout status deploy/milvus-standalone --timeout=15m || true
	@kubectl get pods -A | (command -v rg >/dev/null 2>&1 && rg -i 'milvus' || cat) || true

k8s-dev-bootstrap:
	@kubectl apply -f k8s/dev/configmap.yaml
	@kubectl apply -f k8s/dev/secret.yaml
	@# Free resources on small clusters while bootstrapping.
	@kubectl scale deploy/rag-api --replicas=0 --ignore-not-found >/dev/null 2>&1 || true
	@kubectl delete pod -l app=rag-api --ignore-not-found >/dev/null 2>&1 || true
	@kubectl delete job/rag-bootstrap --ignore-not-found
	@kubectl apply -f k8s/dev/bootstrap-job.yaml
	@kubectl wait --for=condition=complete job/rag-bootstrap --timeout=30m
	@kubectl logs job/rag-bootstrap

k8s-dev-apply:
	@kubectl apply -f k8s/dev/

k8s-dev-up: docker-build k8s-dev-load-image
	@echo "Deploying rag-api (Milvus Lite + Ollama sidecar) ..."
	@$(MAKE) k8s-dev-apply
	@kubectl rollout status deploy/rag-api --timeout=20m

k8s-dev-down:
	@kubectl delete -f k8s/dev/ --ignore-not-found

k8s-dev-status:
	@kubectl get pods,svc,job | rg -n 'rag-api|rag-bootstrap|milvus' || true

k8s-dev-logs:
	@echo "API logs:"
	@kubectl logs deploy/rag-api -c rag-api --tail=200 || true
	@echo ""
	@echo "Ollama logs:"
	@kubectl logs deploy/rag-api -c ollama --tail=200 || true

compose-up:
	@if [ -z "$(COMPOSE)" ]; then \
		echo "ERROR: Docker Compose is not installed."; \
		echo "Install one of:"; \
		echo "  - Docker Desktop (includes 'docker compose')"; \
		echo "  - or 'docker-compose' via Homebrew: brew install docker-compose"; \
		exit 1; \
	fi
	@$(COMPOSE) up --build

compose-down:
	@if [ -z "$(COMPOSE)" ]; then \
		echo "ERROR: Docker Compose is not installed."; \
		exit 1; \
	fi
	@$(COMPOSE) down -v

smoke-compose:
	@SMOKE_BASE_URL=$(SMOKE_BASE_URL) bash scripts/smoke.sh

up: compose-up
	@:

down: compose-down
	@:

api:
	@PYTHONPATH=$(PROJECT_ROOT)/src $(PY) -m uvicorn api.app:app --reload --port 8000

dev: api
	@:

bootstrap:
	@$(PY) scripts/bootstrap_collection.py

# THUCNews + XLSX ingestion helpers (repro after `make clean`)
THUCNEWS_CNEWS_TRAIN ?= data/THUCNews/cnews.train.txt
THUCNEWS_SAMPLE_DIR ?= data/THUCNews/sample_2000
THUCNEWS_MAX_DOCS ?= 2000
COMPANY_XLSX ?= data/target/company.xlsx

thucnews-sample-2000:
	@$(PY) scripts/shard_thucnews_cnews.py --input "$(THUCNEWS_CNEWS_TRAIN)" --out "$(THUCNEWS_SAMPLE_DIR)" --max-docs "$(THUCNEWS_MAX_DOCS)" --balanced

# Fresh recreate + ingest THUCNews 2k sample into the default collection.
reingest-thucnews-2000:
	@$(PY) reingest_thucnews.py --sample-jsonl "$(THUCNEWS_SAMPLE_DIR)/train.sample.jsonl" --max-docs "$(THUCNEWS_MAX_DOCS)" --recreate

# Append company.xlsx into the default collection.
reingest-company-xlsx:
	@$(PY) reingest_company_xlsx.py --xlsx "$(COMPANY_XLSX)"

# Remove generated files to make the repo small and shareable.
# - `clean-lite` keeps `.venv/`
# - `clean` also removes `.venv/` (recreate with `make install`)
# - `clean-docker` removes docker-compose volumes (includes Milvus/MinIO/Ollama data)
clean-lite:
	@echo "Cleaning generated artifacts (keeping .venv/)..."
	@rm -rf .ruff_cache .pytest_cache .mypy_cache .cache .hypothesis \
		dist build htmlcov .coverage .coverage.* *.egg-info \
		traces logs
	@rm -f milvus.db .milvus.db.lock entity_fts.sqlite entity_fts.sqlite-wal entity_fts.sqlite-shm
	@find . -type d -name "__pycache__" -prune -exec rm -rf {} + >/dev/null 2>&1 || true
	@find . -type f -name "*.py[co]" -delete >/dev/null 2>&1 || true
	@find . -type f -name ".DS_Store" -delete >/dev/null 2>&1 || true
	@find . -type f -name "*.log" -delete >/dev/null 2>&1 || true

clean-deps:
	@echo "Removing local dependencies (.venv/)..."
	@rm -rf "$(VENV)"

clean: clean-lite clean-deps
	@echo "Clean complete."

clean-docker:
	@if [ -z "$(COMPOSE)" ]; then \
		echo "Skipping docker cleanup (docker compose not installed)."; \
	else \
		echo "Stopping docker-compose and removing volumes..."; \
		$(COMPOSE) down -v --remove-orphans; \
	fi

clean-all: clean clean-docker
	@:

reingest-chinook-mysql:
	@$(PY) reingest_chinook_mysql.py

eval_ablate:
	@PYTHONPATH=$(PROJECT_ROOT)/src $(PY) eval/runner.py --db-uri "$${DB_URI}" --modes "bm25,prf,qexp" --k 10

ci_gate:
	@bash scripts/ci_eval_gate.sh


