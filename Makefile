.PHONY: help preview preview-check evidence test test-focused frontend-build verify \
	etl-certify etl-live-certify judge-demo judge-demo-check judge-static \
	judge-fireworks-live judge-amd-live

AMD_RUNTIME_EVIDENCE_FILE ?= /tmp/amd-runtime.json

help:
	@echo "Govern.ai"
	@echo ""
	@echo "make preview        # start zero-spend local product view"
	@echo "make preview-check  # verify a running local preview"
	@echo "make test          # run the full backend regression suite"
	@echo "make evidence       # write no-secret capability evidence package"
	@echo "make verify         # focused backend tests + frontend production build"
	@echo "make judge-demo      # start seeded zero-spend Docker judge stack"
	@echo "make judge-demo-check # verify the running judge stack and seeded state"
	@echo "make etl-certify    # execute synthetic governance ETL + notebook gates"
	@echo "make etl-live-certify # verify live pgvector + MinIO and curate evidence"
	@echo "make judge-static   # prove the no-secret hackathon deployment contract"
	@echo "make judge-fireworks-live # verify Fireworks auth with injected credentials"
	@echo "make judge-amd-live # capture Compose AMD runtime and run the live judge gate"

preview:
	bash scripts/local_preview.sh

preview-check:
	bash scripts/preview_healthcheck.sh

evidence:
	cd backend && python3 -m scripts.generate_capability_evidence --output ../capability-evidence.json

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -p pytest_asyncio.plugin backend/tests -q

test-focused:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -p pytest_asyncio.plugin \
		backend/tests/test_capability_registry.py \
		backend/tests/test_capability_evidence_package.py \
		backend/tests/test_api_integration.py \
		backend/tests/test_cost_control_certifier.py \
		backend/tests/test_a2a_protocol_surface.py \
		backend/tests/test_hierarchical_crewai.py \
		backend/tests/test_ops_overview.py \
		backend/tests/test_resume_jobs.py \
		backend/tests/test_eval_goldens.py \
		backend/tests/test_agentic_behaviors.py \
		backend/tests/test_naive_baselines.py \
		-q

frontend-build:
	cd frontend && npm run build

verify: test-focused frontend-build

judge-demo:
	docker compose -f docker-compose.yml -f docker-compose.hackathon.yml up --build

judge-demo-check:
	bash scripts/hackathon_walkthrough.sh

etl-certify:
	cd backend && python3 -m scripts.certify_hackathon_synthetic_data \
		--out ../hackathon-evidence/synthetic-data-certification.json
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -p pytest_asyncio.plugin \
		backend/tests/test_etl_notebook.py \
		backend/tests/test_hackathon_datasets.py \
		-q

etl-live-certify:
	cd backend && python3 -m scripts.certify_etl_integrations \
		--out ../docs/evidence/local-etl-integration.json

judge-static:
	python3 scripts/preflight_amd_gemma_judge.py --mode static

judge-fireworks-live:
	cd backend && python3 -m scripts.verify_hackathon_env --mode fireworks-auth
	cd backend && python3 -m scripts.fireworks_smoke --enable-cost-tracking
	cd backend && python3 -m scripts.byok_smoke --provider fireworks --json

judge-amd-live:
	python3 scripts/capture_amd_runtime_evidence.py \
		--target docker-compose \
		--out "$(AMD_RUNTIME_EVIDENCE_FILE)"
	python3 scripts/preflight_amd_gemma_judge.py \
		--mode live \
		--amd-runtime-evidence "$(AMD_RUNTIME_EVIDENCE_FILE)"
