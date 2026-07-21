# Quickstart

The `0.3.0` Phase 1 release candidate was controller-accepted
on 2026-07-20 after independent read-only `opencode-go/grok-4.5` (`high`)
evaluation returned PASS. It remains unreleased and unpublished; its bounded
live connector proof is compatibility evidence, not traffic, ranking,
conversion, causality, or production evidence. These source commands exercise
the candidate only; they do not publish, contact a provider, or mutate a site.

```console
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/evidence-loop validate --input examples/normal.json
.venv/bin/evidence-loop normalize --input examples/connector-envelope.json --as-of 2026-12-31T00:00:00Z --output work/normalized
.venv/bin/evidence-loop validate --input work/normalized/normalized.json
.venv/bin/evidence-loop run --input examples/normal.json --output work/normal
.venv/bin/evidence-loop demo --output work/demo
.venv/bin/evidence-loop benchmark
```

The input is a strict JSON document containing reserved example sites, evidence
items, and opportunities. An opportunity references one or more evidence IDs.
The run emits `run.json` and, for a non-blocked state, `last-success.json`.
Inspect IDs, terminal state, and safety flags; no metric values are included in
CLI summaries.

`normalize` accepts one or more sanitized Connector Exchange Envelope v1
files, validates them offline, and writes a deterministic schema-version-2
document. Schema version `1` input remains compatible. Normalization creates
empty opportunities, so the resulting observation is a clean no-op until a
separate public opportunity input is supplied.
