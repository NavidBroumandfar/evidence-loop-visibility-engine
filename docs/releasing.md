# Releasing

Releases are maintainer operations. Contributors do not need PyPI credentials.

Version `0.3.0` Phase 1 was controller-accepted
on 2026-07-20 after independent read-only `opencode-go/grok-4.5` (`high`)
evaluation returned PASS and passed the external GitHub release gates. Its
bounded live connector proof is compatibility evidence, not traffic, ranking,
conversion, causality, or production evidence. Future releases must repeat the
contract below with explicit external release authority.

## Contract

- A GitHub release is the only publication trigger.
- The tag must equal `v<package version>`, resolve to the release commit, and
  belong to `main`.
- A successful `public-checks` run for that exact commit is required, and the
  release job reruns the full local gate.
- The `build` job creates each artifact once, validates those exact files, and
  records their SHA-256 digests before upload.
- A separate `verify` job with no OIDC authority verifies the complete file set
  and those digests after download.
- The `publish` job uses PyPI Trusted Publishing through GitHub OIDC.
- The OIDC-enabled `publish` job runs no repository-controlled code; it only
  downloads the immutable workflow artifact and invokes the pinned publisher.
- This workflow does not read or consume a long-lived PyPI API token.
- The GitHub `pypi` environment must be limited to tags matching `v*` and must
  require maintainer review before the first release is published.
- Package versions and Git tags must match for an authorized release. Version
  `0.3.0` is an immutable GitHub release whose PyPI workflow stopped at the
  test gate; `0.3.1` is the corrective package release.
- Published files are immutable. A failed release is repaired with a new
  version; an existing version is never overwritten.

The Trusted Publisher identity is exact:

- PyPI project: `evidence-loop-visibility-engine`
- GitHub owner: `NavidBroumandfar`
- GitHub repository: `evidence-loop-visibility-engine`
- Workflow: `publish-pypi.yml`
- Environment: `pypi`

## Maintainer checklist

1. Confirm the immutable final candidate identity in an external acceptance
   record and obtain controller closure, then obtain explicit authority for the
   external release action. Record an independent evaluation only when one was
   actually authorized and run; do not embed a self-referential final
   fingerprint in the candidate tree.
2. Confirm `main` is clean, synchronized, and green.
3. Confirm the changelog, package version, citation version, and new tag
   agree; do not treat an unreleased checkpoint heading as a release.
4. Run `make check` and `python scripts/artifact_smoke.py` locally.
5. Validate root `action.yml` syntax, full-SHA external Action pinning,
   least-privilege usage, and the synthetic Action-equivalent artifact set.
   A local result is not a hosted GitHub Actions run.
6. Confirm the pending or existing PyPI Trusted Publisher matches the identity
   above exactly.
7. Verify the GitHub `pypi` environment still has the required `v*` deployment
   policy and maintainer review.
8. Publish the matching GitHub release and approve the protected `pypi`
   deployment after reviewing the build job.
9. Verify the package page and install the published version in a clean
   environment.

This workflow publishes only the offline public package. It does not run a
provider adapter, access a website, or grant authority to mutate an external
system.
