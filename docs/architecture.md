# Architecture

The package has four small layers:

1. `schema.py` reads exact bytes, rejects duplicate keys and non-finite JSON,
   enforces bounded public JSON, validates lineage, and checks path/string
   safety.
2. `capabilities.py` is the only router. It exposes eight versioned,
   allowlisted modules and never imports arbitrary installed code.
3. `engine.py` executes one in-memory cycle: Observe fresh evidence, Choose
   one eligible opportunity per site, Act by creating a proposal, independently
   Verify its exact lineage/router/approval boundary, and Record a receipt.
4. `cli.py` exposes value-free summaries for validation, a run, synthetic demo,
   and benchmark.

The engine can only emit proposals. It has no HTTP client, browser driver,
provider SDK, credential lookup, subprocess, or site writer. A caller that
needs to apply a proposal must implement a separate, explicitly approved lane.
The data contracts are the extension points; live adapters and executors do
not become runtime plugins. See the [open-core boundary](open-core-boundary.md).

## Data flow

```text
exact JSON bytes -> strict document -> per-site deterministic choice
           -> proposal (approval_required=true, mutation_allowed=false)
           -> terminal receipt -> atomic run.json/last-success.json
```

Global unsafe file, schema, path, or output conditions fail before a receipt is
written. A semantic capability failure is represented as `blocked` for that
site, so an independent site can still produce an accepted proposal.
