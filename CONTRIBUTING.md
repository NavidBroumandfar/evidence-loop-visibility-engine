# Contributing

Thank you for helping improve the reference implementation. Keep pull
requests focused and explain any contract change.

Before opening a pull request:

```console
make check
.venv/bin/python -m evidence_loop demo --output work/demo
.venv/bin/python -m evidence_loop benchmark
.venv/bin/pip install -e '.[release]'
.venv/bin/python scripts/artifact_smoke.py
```

Use standard-library Python only. Add deterministic tests for safety and
lineage changes. Do not include private data, credentials, live endpoints,
generated artifacts, or claims about rankings, traffic, answers, or citations.
Changes that would add an external integration need an explicit design and
approval boundary first.
