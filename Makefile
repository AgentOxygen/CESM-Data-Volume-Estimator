.PHONY: test build dev shell import

DC = docker compose run --rm dev

# Run the test suite.
test:
	$(DC) pytest -q

# Regenerate docs/data.json from data/*.yaml. Commit the result.
build:
	$(DC) python estimator.py build

# Serve the site at http://localhost:8000, rebuilding docs/data.json whenever
# data/*.yaml changes. The page reloads itself when either changes.
dev:
	docker compose run --rm --service-ports dev python tools/dev.py

shell:
	$(DC) bash

# One-time reseed of data/*.yaml from the reference CSV. You almost never want
# this -- it overwrites hand-maintained files. See tools/import_csv.py.
import:
	$(DC) python tools/import_csv.py
