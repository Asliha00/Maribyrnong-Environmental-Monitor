# Thin wrappers so `make dev` / `make test` work on Linux, macOS and CI.
# On Windows without make, run the command shown after each target directly.
PY ?= $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python,$(if $(wildcard .venv/bin/python),.venv/bin/python,python3))

.PHONY: install env db seed dev test test-backend test-frontend e2e lint audit

install:        ## python -m pip install -e ".[dev]" && npm ci --prefix frontend
	$(PY) -m pip install -e ".[dev]"
	npm ci --prefix frontend

env:            ## python scripts/init_env.py
	$(PY) scripts/init_env.py

db:             ## python data_pipeline/etl.py --sqlite --rebuild
	$(PY) data_pipeline/etl.py --sqlite --rebuild

seed:           ## python backend/scripts/seed_users.py (demo accounts from SEED_* in .env)
	$(PY) backend/scripts/seed_users.py

dev:            ## python scripts/dev.py
	$(PY) scripts/dev.py

test: test-backend test-frontend

test-backend:   ## python -m pytest --cov
	$(PY) -m pytest --cov --cov-report=term-missing

test-frontend:  ## npm test --prefix frontend
	npm test --prefix frontend

e2e:            ## cd e2e && npm ci && npx playwright install chromium && npx playwright test
	cd e2e && npm ci && npx playwright install chromium && npx playwright test

lint:           ## ruff check backend scripts && npm run lint --prefix frontend
	$(PY) -m ruff check backend scripts
	npm run lint --prefix frontend

audit:          ## pip-audit . (pyproject dependencies) && npm audit --audit-level=high
	$(PY) -m pip_audit .
	npm audit --audit-level=high --prefix frontend
