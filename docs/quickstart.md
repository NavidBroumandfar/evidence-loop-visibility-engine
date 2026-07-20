# Quickstart

```console
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/evidence-loop validate --input examples/normal.json
.venv/bin/evidence-loop run --input examples/normal.json --output work/normal
.venv/bin/evidence-loop demo --output work/demo
.venv/bin/evidence-loop benchmark
```

The input is a strict JSON document containing reserved example sites, evidence
items, and opportunities. An opportunity references one or more evidence IDs.
The run emits `run.json` and, for a non-blocked state, `last-success.json`.
Inspect IDs, terminal state, and safety flags; no metric values are included in
CLI summaries.
