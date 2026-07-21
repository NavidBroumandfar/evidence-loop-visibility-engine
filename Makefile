.PHONY: check test compile scan demo benchmark artifact-smoke

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

test:
	$(PYTHON) -m unittest discover -s tests -v

compile:
	$(PYTHON) -m compileall -q src tests scripts

scan:
	$(PYTHON) scripts/validate_public_release.py

demo:
	$(PYTHON) -m evidence_loop demo --output work/demo

benchmark:
	$(PYTHON) -m evidence_loop benchmark

artifact-smoke:
	$(PYTHON) scripts/artifact_smoke.py

check: test compile scan
