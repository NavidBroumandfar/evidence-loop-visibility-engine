# Open-core boundary

Evidence Loop Visibility Engine is a complete and useful public core. It can
validate bounded evidence, make a deterministic choice, produce a proposal,
verify the proposal boundary, and record an auditable receipt entirely
offline. The Apache-2.0 package is not artificially limited to create lock-in.

The public repository deliberately stops before live operation. That boundary
keeps its behavior reproducible and its claims inspectable.

## What the public core owns

- Strict synthetic input validation and evidence lineage.
- Deterministic opportunity selection and allowlisted proposal routing.
- Fail-closed proposal verification and isolated site lanes.
- Atomic receipts, explicit terminal states, fixtures, and conformance cases.
- An offline CLI with no site mutation or provider access, including local
  Connector Exchange Envelope v1 normalization in the controller-accepted,
  unreleased Phase 1 checkpoint.

## What may exist around the core

A private or managed operator can add value through provider-specific adapters,
calibrated evidence and history, evaluation and operator judgment, team
workflows, or managed operation. Those advantages are operational context, not
hidden requirements for the public package. They do not make a public proposal
proof of a ranking, traffic, answer, citation, or conversion outcome.

No private system is described, linked, or required by this repository.

## Extension points

The stable handoff is data, not an import boundary:

1. A separate collector can produce a document that satisfies the public
   schema and safety constraints.
2. A separate reviewer can inspect the proposal and its digest-bearing
   receipt.
3. A separately approved executor can translate an accepted proposal into an
   action in its own isolated process.
4. Later evidence can return through the same public input contract for a new
   bounded cycle.

Provider-specific adapters and executors should remain outside the installed
runtime. They need their own permissions, privacy review, calibration, audit
trail, and explicit approval gates. The public engine never grants those
capabilities. Generic deterministic envelope normalization—grouping, field
translation, and digest computation—is Phase 1 release-candidate core logic,
not provider-specific adapter logic. See
[connector-contract.md](connector-contract.md).

## Phase 1 release candidate — Envelope normalization in the core

The `0.3.0` controller-accepted release candidate includes a
deterministic, offline envelope validator and normalizer. Independent
read-only `opencode-go/grok-4.5` (`high`) evaluation returned PASS on
2026-07-20. It remains unreleased and unpublished; it is compatibility
evidence, not traffic, ranking, conversion, causality, or production evidence. The candidate
accepts only sanitized, credential-free envelopes from separately distributed
connectors and translates them into documents the core accepts. Credentials and private provider
identifiers must never intentionally enter the envelope or the core. The core
neither reads an OS secret store nor requests credentials; credential-shaped
content causes rejection of the whole envelope before normalization, evidence,
output, rendering, or persistence. The normalizer makes no network, provider,
subprocess, or credential calls. Provider-specific authentication, transport,
raw provenance, and collection remain in separate opt-in connector
distributions. See [ROADMAP.md](../ROADMAP.md) and
[connector-contract.md](connector-contract.md).

## Clean-room rule

Public contributions must be designed from the public contract and public
evidence only. Do not copy, import, link, or reconstruct non-public source,
configuration, data, identifiers, operational history, or implementation
details. If a contributor has seen non-public material, they must still
produce an independently justified implementation from public requirements
and document the public rationale.

When in doubt, keep the integration outside this repository and communicate
through the documented input and receipt formats.
