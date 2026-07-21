# Companion GitHub Action

> **Status: Codex-validated Phase 3 release candidate with hosted synthetic
> GitHub execution proof (2026-07-22).** It remains unreleased and unpublished.
> Push and pull-request jobs passed at candidate commit `bfa544e` with
> `clean-no-op` and `external_calls=0`; no model, evaluator, provider,
> credential, publication, or deployment call occurred in the Action job.

The root `action.yml` executes the public core directly from the immutable
Action checkout without package installation, validates sanitized Connector Exchange
Envelope v1 files, normalizes them with an explicit UTC bound, and runs the
engine exactly once. It does not bundle or invoke a connector.

## Inputs

| Input | Required | Boundary |
| --- | --- | --- |
| `envelope-directory` | Yes | Repository-relative directory containing only one to 200 direct regular `.json` files with bounded safe names. |
| `as-of` | Yes | Explicit real UTC timestamp such as `2026-12-31T00:00:00Z`. Evidence collected later than this bound is rejected. |
| `output-directory` | No | New, repository-relative, non-overlapping directory. Default: `evidence-loop-action-output`. |

Absolute caller paths, traversal, symlinks, nested directories, non-JSON
entries, existing output, malformed JSON, duplicate keys, unsafe strings,
credential/private-ID shapes, invalid digest roles, excessive size/depth/
cardinality, future evidence, and ambiguous metadata configuration fail
closed before approved artifact upload.

The Action validates the named provider-response digest's shape and exact
preservation, and it recomputes the normalized document and receipt digests.
Because the sanitized envelope intentionally carries no raw provider-response
bytes, the Action cannot independently recompute `provider_response_sha256`;
that raw-byte binding remains the separately reviewed connector's
responsibility.

## Outputs and artifact surface

The Action exposes only `terminal-state`, `input-digest`,
`receipt-sha256`, and `external-calls=0`. The fixed
`evidence-loop-receipt` artifact is retained for seven days and contains:

- `normalized.json`
- `run.json`
- `last-success.json` only when the terminal state is not `blocked`

Normalization creates no opportunities. An envelope-only Action run is
therefore an honest `clean-no-op`; it never invents a recommendation. The
installed core's direct document interface retains the existing
`approval-required`, `clean-no-op`, and `blocked` semantics. A blocked
Action receipt is uploaded before the composite Action returns exit code 3.

## Least-privilege usage after an authorized release

Replace `FULL_COMMIT_SHA` with the exact reviewed Action commit. Do not use a
moving branch reference.

```yaml
permissions:
  contents: read

steps:
  - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
  - uses: NavidBroumandfar/evidence-loop-visibility-engine@FULL_COMMIT_SHA
    with:
      envelope-directory: evidence-loop-envelopes
      as-of: 2026-12-31T00:00:00Z
      output-directory: evidence-loop-action-output
```

The caller must not pass provider credentials into this Action step. A
separate connector may create the sanitized envelope in its own isolated,
explicitly authorized job or process, but the connector and its credentials
remain outside this Action and the installed core.

GitHub's pinned Python setup and artifact upload are declared workflow
infrastructure. They do not change the evidence-loop receipt's
`external_calls=0`: the installed normalizer and engine make zero provider,
network, browser, credential, subprocess, publication, or site-mutation calls.
