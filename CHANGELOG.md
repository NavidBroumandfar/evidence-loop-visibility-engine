# Changelog

## 0.3.0 - 2026-07-22

- Controller-accepted local Phase 1 implementation checkpoint (2026-07-20)
  after independent read-only `opencode-go/grok-4.5` (`high`) evaluation
  returned PASS. Immutable candidate identities stay outside the candidate
  tree rather than creating a self-referential inline fingerprint. Added
  offline Connector Exchange Envelope v1
  normalization and schema version `2`, while retaining schema version `1`
  compatibility.
- Added deterministic connector evidence identity validation, strict window
  ordering, separate digest purposes, and fail-closed regression coverage.
- Confirmed the separately distributed Vercel connector's current read-only
  provider response contract and sanitized envelope-to-core round trip, then
  released that connector on GitHub as `v0.1.0`. No
  live values, credentials, or private provider identifiers enter this public
  repository or its Action.
- Fixed the local `make check` gate to prefer an existing `.venv` interpreter
  while retaining the system-Python fallback used by CI.
- Added a Phase 3 companion GitHub Action candidate. It executes directly
  from the immutable Action checkout without package installation, accepts only a
  bounded repository-relative directory of sanitized Connector Exchange
  Envelope v1 JSON files, requires an explicit UTC bound, executes one
  offline cycle, and uploads only the normalized document and core receipts.
  External Action dependencies are commit-pinned and the documented workflow
  permission is read-only. Hosted push and pull-request workflows passed the
  Action job at candidate commit `bfa544e` with synthetic inputs,
  `clean-no-op`, and `external_calls=0`; no provider call, credential,
  publication, or deployment occurred in that job.
- The bounded live connector proof establishes read-only contract compatibility,
  not traffic, ranking, conversion, causality, or production outcomes.

## 0.2.0 - 2026-07-20

- Added an original evidence-loop system visual and matching social card.
- Clarified the complete offline public core, private/managed operator
  boundary, clean-room rule, and data-contract extension points.
- Improved README positioning and navigation without changing runtime
  behavior or external-outcome claims.

## 0.1.0 - 2026-07-20

- Initial public reference implementation.
- Added strict offline multi-site loop, allowlisted capability router, atomic
  receipts, synthetic fixtures, benchmark, documentation, and release scanner.
