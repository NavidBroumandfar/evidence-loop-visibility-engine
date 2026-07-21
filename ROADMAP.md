# Roadmap

Phase 1 has a controller-accepted `0.3.0` release candidate as
of 2026-07-20, after independent read-only `opencode-go/grok-4.5` (`high`)
evaluation returned PASS. Immutable candidate identities are recorded outside
the candidate tree so editing a truth document cannot invalidate a fingerprint
embedded in that same content.
It remains unreleased and unpublished, and is not provider, traffic, ranking,
conversion, causality, or production-outcome evidence. Phase 2 has a separately
distributed release candidate with bounded read-only live compatibility proof.
Phase 3 has a companion Action release candidate that still requires hosted
GitHub execution. Phase 4 and later remain planned. Status may change based on
access, API availability, and operator feedback.

## Phase 1 — Connector contract and normalization (in the installed core)

**Status:** Controller-accepted release candidate (2026-07-20) — unreleased
and unpublished

The checkpoint accepts sanitized Connector Exchange Envelope v1 files through
the `normalize` command and produces a core-valid schema version `2` document.
It validates canonical public origins, credential-shaped content, bounded
measures and lineage, strict observation/comparison windows, deterministic
evidence identity, and separate provider-response and input digests. It keeps
schema version `1` behavior and committed fixtures compatible. Normalization
creates empty opportunities and therefore yields a clean no-op unless a
separate public opportunity input is present.

The checkpoint remains deterministic, offline, standard-library-only, and
generic: it has no HTTP, credentials, SDKs, subprocesses, provider logic, or
site writes. Connectors remain separate and opt-in. This implementation is a
controller-accepted release candidate, not a released capability or
provider, live, or production evidence.

See [docs/connector-contract.md](docs/connector-contract.md).

## Phase 2 — Vercel Analytics companion

**Status:** Released separately on GitHub as `v0.1.0` (2026-07-22); PyPI
publication remains gated. At the owner's direction, its
maintenance closure used deterministic controller checks only and made no
OpenCode or other model-evaluator call. A bounded read-only live validation
confirmed the current Vercel response contract and sanitized envelope-to-core
round trip; no live data, credential, or provider identifier entered this
repository.

A separate, opt-in connector collects Vercel Analytics `visits/count`
evidence and emits an envelope conforming to the connector contract.
Credentials remain scoped to the connector process and never enter the core or
Git. A required process-only public site binding must match the requested site
before transport, while project and team identifiers remain request-only. Its
current proof is synthetic/fake-transport and artifact validation, not a
provider mutation or production result. The live proof establishes read-only
API compatibility, not traffic, ranking, conversion, or causality.

Repository: [evidence-loop-vercel-web-analytics-connector](https://github.com/NavidBroumandfar/evidence-loop-vercel-web-analytics-connector)

## Phase 3 — Companion GitHub Action

**Status:** Codex-validated release candidate (2026-07-21) — unreleased,
unpublished, and not yet dispatched on GitHub. At the owner's
direction this phase used local deterministic Codex checks only and made no
OpenCode, model, evaluator, provider, or GitHub API call.

A GitHub Action that validates and normalizes an envelope using the installed
public core's normalizer, then operates one bounded evidence loop cycle.
The Action does **not** bundle or invoke provider connectors; each connector
remains a separate, opt-in step that produces the envelope file the Action
consumes.

Action flow:

1. Validate the envelope against the connector contract.
2. Normalize the envelope using the core's installed normalizer (credential
   rejection, field translation, digest preservation).
3. Run one bounded evidence loop cycle with the normalized document.

The bounded loop execution receives no provider credentials and makes zero
provider requests.

The Action provides:

- Envelope validation and normalization before the core runs.
- Deterministic `run` or `validate` execution with receipt output as workflow
  artifacts.
- May install declared dependencies and upload approved artifacts as standard
  GitHub workflow infrastructure. The Action's evidence-loop execution itself
  makes zero provider requests and receives no provider credentials.

The candidate accepts one explicit repository-relative directory whose
direct children must be bounded regular `.json` files with safe names. It
rejects traversal, absolute input/output configuration, symlinks, nested or
non-JSON entries, existing or overlapping output, malformed/oversized/deep or
over-cardinality envelopes, credential/private-ID shapes, invalid digest
roles, future evidence, unsafe GitHub output metadata, and ambiguous arguments
before approved artifact upload.

The Action installs the public core from its own immutable checkout with
package-index access disabled. Its external `setup-python` and
`upload-artifact` steps are pinned to full commit SHAs. The caller retains a
least-privilege `contents: read` permission boundary. It writes exactly
`normalized.json`, `run.json`, and, for a non-blocked terminal state,
`last-success.json`, then uploads that fixed directory for seven days.
Normalization never invents opportunities, so envelope-only execution is a
truthful `clean-no-op`; the underlying core still preserves its existing
`approval-required`, `clean-no-op`, and `blocked` semantics for valid
core documents.

Local proof includes focused Action tests, socket-denied synthetic
Action-equivalent execution, full public checks, static Action/YAML security
review, and installed wheel/sdist Action-equivalent smoke. It is not a GitHub
hosted run, publication, release, provider compatibility test, or production
result. See [docs/github-action.md](docs/github-action.md).

## Phase 4 — Google Search Console connector

**Status:** Planned

A separate, opt-in connector for Search Console evidence. Subject to API access
and quota constraints. Envelope conforms to the connector contract; no ranking
or traffic outcome is claimed.

## Phase 5 — Google Analytics 4 connector

**Status:** Planned

A separate, opt-in connector for GA4 measurement evidence. Subject to API
access and Data API availability. Envelope conforms to the connector contract;
no conversion or traffic outcome is claimed.

## Phase 6 — Bing Webmaster Tools connector

**Status:** Planned — gated on API access confirmation

A separate, opt-in connector for Bing Webmaster Tools evidence. This phase
proceeds only after confirmed API access and a stable public endpoint. Envelope
conforms to the connector contract; no ranking or visibility outcome is
claimed.

## Phase 7 — Versioned releases and launch

**Status:** Planned

Stable versioned releases of the public core and companion components.
Sequence depends on connector maturity, contract stability, and operator
readiness.

## Principles

- The public core remains deterministic, offline, and stdlib-only at every
  phase.
- Connectors are always separate, opt-in, and never bundled with the installed
  package.
- No item on this roadmap claims or implies a ranking, traffic, answer
  inclusion, citation, or conversion outcome.
- Planned items may be reordered, deferred, or removed without notice.
