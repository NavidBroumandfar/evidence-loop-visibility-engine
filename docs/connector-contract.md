# Connector contract

This document describes the clean-room boundary between the Evidence Loop
core release candidate and separately distributed provider connectors.

> **Status: controller-accepted `0.3.0` Phase 1 release candidate
> (2026-07-20).** Independent read-only
> `opencode-go/grok-4.5` (`high`) evaluation returned PASS. The candidate
> remains unreleased and unpublished. Its bounded live connector proof is
> compatibility evidence, not traffic, ranking, conversion, causality, or
> production evidence.

## Local checkpoint core input schemas (0.3.0, unreleased)

The local `evidence-loop` checkpoint accepts strict public schema versions `1`
and `2`:

- Top-level keys allowed: `schema_version`, `run_id`, `input_digest`, `sites`.
  Required: `schema_version`, `sites`. Optional: `run_id`, `input_digest`.
- Each site carries `site_id`, `site`, `evidence`, `opportunities`.
- Schema version `1` evidence uses `observed_at` (ISO-8601 UTC), `completeness`
  (`complete`, `partial`, `missing`), `freshness` (`fresh`, `stale`,
  `expired`), and `uncertainty` (`low`, `medium`, `high`).
- Schema version `1` retains its reserved-example URL contract and
  compatibility behavior. Schema version `2` is produced by the local
  normalizer, permits canonical public HTTPS origins, preserves connector
  `unknown` states, and requires both `input_digest` and per-evidence
  `provider_response_sha256` under their exact names.
- Schema version `1` site URLs must use reserved example domains (`example.com`, `*.example`,
  `*.test`, `*.invalid`).
- Unknown fields are rejected. Credential-like strings, private paths, and
  token-like hex values are rejected by the safety scanner.

Envelope fields are accepted only by the local `normalize` boundary, never as
unvalidated schema-version-1 input.

## Invariants

- The installed `evidence-loop` package remains deterministic, offline, and
  standard-library-only. Credentials and private provider identifiers must
  never intentionally enter the envelope or the core. The core neither reads
  an OS secret store nor requests credentials.
- Provider connectors are **separately distributed** components. They may
  privately authenticate with a provider, fetch evidence, and emit a validated
  JSON envelope.
- The local Phase 1 checkpoint normalizer validates the connector envelope and
  translates it into a schema-version-2 document the core accepts.
  Credential-shaped content causes rejection of the whole envelope before
  normalization, evidence, output, rendering, or persistence. The normalizer
  receives only a sanitized, credential-free envelope and makes no network,
  provider, subprocess, or credential calls.
- Named opaque underscore-prefixed provider/private identifier shapes are
  rejected across provider, property, project, team, account, tenant,
  workspace, organization, user, session, and abbreviated provider-ID
  families. Canonical UUID-shaped values and file URI paths are also rejected.
  Human aliases such as `team-plan`, `project-plan`, `properties-summary`, and
  `public-alpha` remain valid. Exact `provider_response_sha256` and
  `input_digest` fields are validated only in their named digest roles.
- Connectors are never imported by, linked into, or bundled with the public
  core. Communication is through data files only.
- No connector may claim that its provider data produces a ranking, traffic,
  answer inclusion, citation, or conversion outcome.

## Connector Exchange Envelope v1

The local checkpoint validates this envelope and deterministically translates
it into schema version `2`. Separately distributed connectors remain
responsible for producing sanitized files; no connector is bundled or invoked.

| Field | Required | Intended semantics |
| --- | --- | --- |
| `schema_version` | Yes | Must match the envelope contract version. Separate from the core's `schema_version`. |
| `source` | Yes | Connector identity. Must be a stable, non-secret string identifying the connector distribution. |
| `provider` | Yes | Upstream provider name. Must be a stable, non-secret string. Separate from `source`. |
| `scope_ref` | Yes | Stable, non-secret, operator-chosen alias for the scope of evidence collection (e.g., a human-readable site label). This is not a provider identifier. Private provider project IDs, property IDs, team IDs, or account IDs remain in connector-local ignored provenance only and never cross into the envelope or the core. |
| `site_id` | Yes | Safe, operator-chosen slug identifying the site for grouping. Lowercase alphanumeric plus hyphens, max 63 characters. One or many envelopes group into sites by exact `site_id` match. |
| `site_url` | Yes | Canonical site HTTPS origin URL. See URL policy below. |
| `observation_window` | When applicable | ISO-8601 interval over which evidence was collected. Its end must be no later than `collected_at`. |
| `comparison_window` | When applicable | ISO-8601 interval used as a baseline for comparison. Its end must be no later than `collected_at`, and no later than the observation start when both windows are present. |
| `collected_at` | Yes | ISO-8601 UTC timestamp of collection. Must not be in the future. The normalization layer maps this to the core's `observed_at`. |
| `grain` | Yes | Declared granularity of the evidence (page-level, site-level, query-level, etc.). |
| `completeness` | Yes | `complete`, `partial`, or `unknown`. The connector must report the provider's actual state; `unknown` is a first-class uncertainty signal, not semantically equivalent to the core's `missing`. |
| `freshness` | Yes | `fresh`, `stale`, or `unknown`. The connector must report the provider's actual state; `unknown` is a first-class uncertainty signal, not semantically equivalent to the core's `expired`. |
| `uncertainty` | Yes | `low`, `medium`, `high`, or `unknown`. The connector must report the provider's actual state; `unknown` is a first-class uncertainty signal, not semantically equivalent to any core enum value. |
| `limitations` | When known | Free-text declaration of known data gaps, sampling bias, or API constraints. |
| `measures` | Yes | Numeric values must be finite. Units must be declared or implied by the evidence type. The normalization layer packages one or more measures into a bounded `facts` measures object with exact finite values and declared units. |
| `lineage` | Yes | Ordered provenance chain from provider response to emitted envelope. Include non-secret request parameters. Reference the `provider_response_sha256` field by exact name; never duplicate the hex value in arbitrary strings. |
| `provider_response_sha256` | Yes | Single required string. Lowercase 64-character hex SHA-256 of the exact raw provider response bytes before any transformation. This is the **provider-response digest**, a distinct purpose from the core's normalized-document `input_digest`. |

Missing or ambiguous required fields must cause the connector to **fail
closed**: emit no envelope rather than a degraded one.

### URL policy (site_url)

The `site_url` field carries a canonical HTTPS origin for site assembly.
Validation rules:

- **Scheme:** must be `https`. No other scheme is accepted.
- **Authority:** must not contain userinfo (`user:pass@`), credentials, or
  authentication tokens.
- **Port:** no explicit port is accepted.
- **Host:** must be a syntactically valid DNS hostname. Reject IP literals
  (v4 and v6), `localhost`, any `localhost` suffix, and syntactically
  invalid DNS hostnames. The core never connects to `site_url`.
- **Path:** must be empty or `/` only. An absent path and a bare slash
  normalize to the same origin form. No query strings (`?...`), fragments
  (`#...`), or credential-shaped path segments are accepted.
- **Private identifiers:** reject hosts or paths that are solely private
  provider identifiers (internal project IDs, property IDs, team IDs).

**Schema version policy:**

- Schema version `1` and all committed or CI fixtures
  retain reserved example domains (`example.com`, `*.example`, `*.test`,
  `*.invalid`).
- The local unreleased Phase 1 checkpoint's schema version `2` may accept real
  public HTTPS origins for local runtime inputs. Committed fixtures and CI
  continue to use reserved example domains.

One or many envelopes for the same site are intentionally allowed and are
grouped by exact `site_id` plus `site_url`. Envelopes sharing `site_id` but
differing `site_url` are rejected. Evidence identity is the exact canonical
nonsecret tuple (`source`, `provider`, `scope_ref`, `site_id`, `site_url`,
`observation_window`, `comparison_window`, `collected_at`, `grain`); if the
same tuple appears more than once, reject the set whether payloads match or
conflict.

## Local normalization boundary (Phase 1 checkpoint)

The local unreleased Phase 1 checkpoint normalizer sits between the connector
envelope and the core input. It performs deterministic, offline, generic
normalization—not provider-specific adapter logic. It does the following:

1. **Validate** the envelope against this contract (size, type, cardinality,
   timestamp bounds, finite numbers, URL policy). The CLI requires an explicit
   UTC `--as-of` collection bound, rejects over-cardinality before loading,
   and stops loading when cumulative raw bytes exceed the public byte limit.
2. **Reject** credential-shaped content. The core neither reads an OS secret
   store nor requests credentials. If the envelope contains API keys, tokens,
   session IDs, private user IDs, or any value that could reconstruct an
   authenticated session, the whole envelope is rejected before normalization,
   evidence, output, rendering, or persistence. This is defense-in-depth:
   connectors must exclude credentials before emission; the core rejects them
   if they arrive regardless.
3. **Group** one or many envelopes into sites by exact `site_id` plus
   `site_url`. Envelopes sharing `site_id` but differing `site_url` are
   rejected. Evidence identity is the exact canonical nonsecret tuple
   defined above; if the same tuple appears more than once, reject the set
   whether payloads match or conflict.
4. **Translate** envelope fields into the core's accepted schema:
   - Map `collected_at` to `observed_at`.
   - Map `site_url` to the core `site` field.
   - Map `site_id` to the core `site_id` field.
   - Assemble each required site object with an `evidence` array and an
     `opportunities` array.
   - Package one or more `measures` into a bounded `facts` measures object
     with exact finite values and declared units.
   - Produce a deterministic safe `evidence_id` as `ev-` plus bounded
     lowercase base32 of a digest over the canonical nonsecret tuple
     (`source`, `provider`, `scope_ref`, `site_id`, `site_url`,
     `observation_window`, `comparison_window`, `collected_at`, `grain`).
     This tuple defines evidence identity. The identifier is stable,
     nonsecret, and not raw 64-hex. Collisions fail closed.
   - Translate envelope `lineage` references into the core's evidence
     lineage, preserving the `provider_response_sha256` field name reference
     without duplicating the hex value in arbitrary strings.
   - Preserve connector `completeness`, `freshness`, and `uncertainty`
     `unknown` values exactly in schema version `2`; never silently map them
     to a semantically different version-1 state (such as `missing`,
     `expired`, or `high`).
5. **Initialize** `opportunities` as empty unless a separate existing public
   opportunity input explicitly supplies them. Observation normalization
   alone yields a clean-no-op until opportunities are separately present; it
   never invents recommendations.
6. **Preserve** both digest purposes without conflation:
   - `provider_response_sha256` — the single required envelope string field
     verifying that the connector received a specific upstream payload.
   - `input_digest` — the separate top-level core field verifying the
     normalized document's canonical integrity.
   Receipts preserve both under their exact names. One must not replace or
   reduce the other. The safety scanner and allowlist must evolve to accept
   both as distinctly named fields, each validated as 64-character lowercase
   hex SHA-256, without weakening the generic rejection of token-like hex
   values.
7. **Produce** `schema_version` and canonical `input_digest` for the
   normalized document.
8. **Produce** a document that passes `validate_document()` in the installed
   core, using the versioned schema that supports the translated uncertainty
   values.

The normalization layer is controller-accepted release-candidate core logic,
not part of separately distributed connector tooling. It remains unreleased
and unpublished; acceptance does not grant provider,
live, production, publication, or release authority. The core normalizer
receives only a sanitized, credential-free envelope and makes no network,
provider, subprocess, or credential calls.

## Connector security invariants

1. **Connector-side credential exclusion.** Credentials are scoped to the
   connector's own process or OS secret store. Credentials and private
   provider identifiers must never intentionally enter the envelope or the
   core. They never appear in Git history, tracked output, public logs, or
   any file consumed by the core.
2. **Core defense-in-depth rejection.** The core rejects credential-shaped
   content. Supported connector output excludes credentials and private
   identifiers. If a hostile or malformed envelope arrives containing API
   keys, tokens, session IDs, private user IDs, or any value that could
   reconstruct an authenticated session, the whole envelope is rejected
   before normalization, evidence, output, rendering, or persistence. The
   core neither reads an OS secret store nor requests credentials.
3. **No secret identifiers in output.** The envelope must not contain API keys,
   tokens, session IDs, private user IDs, or any value that could reconstruct
   an authenticated session.
4. **Strict validation.** The connector validates envelope size, type,
   cardinality, and timestamp bounds before writing. Oversized, malformed, or
   out-of-range values fail closed.
5. **Fail closed on ambiguity.** If the provider response is incomplete,
   ambiguous, or structurally unexpected, the connector emits no envelope and
   reports a structured error to its own operator log.
6. **Explicit external-action authority.** A connector fetches evidence only.
   It does not mutate a site, publish content, submit sitemaps, or perform any
   write operation against a provider unless the operator explicitly authorizes
   that action in a separate, audited step.
7. **No bearer-credential redirects.** A connector must not follow HTTP
   redirects while carrying bearer credentials unless the redirect target is
   rigorously verified as the same origin.
8. **No outcome overclaim.** A connector must not annotate its envelope with
   ranking, traffic, citation, or causality predictions. Evidence is
   observation, not outcome.

## Versioning

This contract is at version `1` in the local checkpoint. Breaking changes to
envelope semantics or security invariants increment the major version.
Additive, backward-compatible fields increment the minor version. Its local
implementation does not constitute a published contract release.

## Testing

Connectors should include their own test fixtures using reserved example
domains (`*.example`, `*.test`). Connector CI must use fake transports and
synthetic fixtures; it must never make live provider API requests. Connector
unit tests do not require the public core to be installed.

Integration tests that verify envelope normalization against a pinned core
version require the public core to be installed. These tests remain offline
and use only synthetic data. Live provider access is never part of connector
CI.

The local checkpoint includes round-trip tests: sanitized envelope →
normalization produces core-valid document → core `validate_document()`
passes. They remain offline and do not establish provider compatibility.

## Integration with the roadmap

The connector contract is the release-candidate foundation for separately
distributed provider companions. Each companion remains a separate, opt-in
component that produces envelopes conforming to this contract. The separate
Vercel companion was released on GitHub as `v0.1.0` after controller validation with
synthetic fixtures, fake transports, and one bounded read-only live
compatibility proof. Its sanitized envelope passed this normalizer and core
with `external_calls=0`; no live value, credential, or provider identifier
entered this repository. PyPI publication remains separately gated. This
checkpoint does not grant provider mutation authority. See [ROADMAP.md](../ROADMAP.md)
for sequencing and the [connector repository](https://github.com/NavidBroumandfar/evidence-loop-vercel-web-analytics-connector).
