.PHONY: install test tables figures numbers amendments panel lint

install:   ## install the package and its test dependencies
	pip install -e ".[dev,xls,stats,gbm,plots,models]"

test:      ## run the test suite, then print the two headline tables
	pytest -q
	@python site/print_tables.py

tables:    ## print the baseline table and the coverage table
	@python site/print_tables.py

numbers:   ## rebuild site/site_numbers.json from the tracked sources
	python site/build_numbers.py

figures:   ## rebuild site/figures/ from site_numbers.json
	python site/build_figures.py

amendments: ## regenerate docs/amendment_log.md from preregistration.md section 10
	python tools/render_amendment_log.py

panel:     ## rebuild the vintage panel from a local archive (needs data/raw, not shipped)
	nhs-ae-ingest build

lint:
	ruff check src tests
