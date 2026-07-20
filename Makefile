.PHONY: check test compile scan demo benchmark artifact-smoke

test:
	python3 -m unittest discover -s tests -v

compile:
	python3 -m compileall -q src tests scripts

scan:
	python3 scripts/validate_public_release.py

demo:
	python3 -m evidence_loop demo --output work/demo

benchmark:
	python3 -m evidence_loop benchmark

artifact-smoke:
	.venv/bin/python scripts/artifact_smoke.py

check: test compile scan
