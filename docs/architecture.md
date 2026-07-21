# Architecture

The `0.3.0` Phase 1 release candidate was controller-accepted
on 2026-07-20 after independent read-only `opencode-go/grok-4.5` (`high`)
evaluation returned PASS. It remains unreleased and unpublished; its bounded
live connector proof is compatibility evidence, not traffic, ranking,
conversion, causality, or production evidence. The Phase 3 companion Action candidate was
added on 2026-07-21 with Codex-only deterministic validation and no model,
provider, credential, or publication action. Hosted synthetic push and
pull-request Action jobs passed at candidate commit `bfa544e`. The candidate
has six small offline layers:

1. `schema.py` reads exact bytes, rejects duplicate keys and non-finite JSON,
   enforces bounded public JSON, validates both schema versions, connector
   evidence identity, lineage, and path/string safety.
2. `normalizer.py` validates credential-free Connector Exchange Envelope v1
   files and deterministically produces schema version `2` documents.
3. `capabilities.py` is the only router. It exposes eight versioned,
   allowlisted modules and never imports arbitrary installed code.
4. `engine.py` executes one in-memory cycle: Observe fresh evidence, Choose
   one eligible opportunity per site, Act by creating a proposal, independently
   Verify its exact lineage/router/approval boundary, and Record a receipt.
5. `cli.py` exposes value-free summaries for validation, normalization, a run,
   synthetic demo, and benchmark.
6. `action_runner.py` and root `action.yml` constrain a caller workspace to
   one safe envelope directory and one new output directory, require an
   explicit UTC bound, call the same installed normalizer and engine once, and
   expose only fixed safe metadata plus the approved normalized/receipt files.
   The composite Action pins external actions and never bundles or invokes a
   provider connector.

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

## Local Phase 1 checkpoint — Normalization layer

The controller-accepted release candidate places deterministic, offline normalization
between separately distributed connector envelopes and the core input. It
performs generic site grouping, field translation, and digest computation—not
provider-specific adapter logic. It is not published, released, or provider
authority. See
[connector-contract.md](connector-contract.md) and
[ROADMAP.md](../ROADMAP.md).

## Local Phase 3 candidate — Companion Action

The Action is an orchestration boundary around the installed public contract,
not a new connector or alternate engine. File enumeration and path containment
occur before envelope loading. Normalization and receipt integrity are checked
in memory before output creation. The output directory must be new, and its
final direct children must exactly match the terminal state's approved file
set. GitHub metadata is limited to terminal state, artifact path, the two
canonical digests, and `external-calls=0`.

The GitHub artifact upload and Python setup are declared workflow
infrastructure. They are distinct from the evidence-loop execution, which has
no network/provider/browser/subprocess/credential path. See
[github-action.md](github-action.md).
