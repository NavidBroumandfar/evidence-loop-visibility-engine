# Releasing

Releases are maintainer operations. Contributors do not need PyPI credentials.

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
- Package versions and Git tags must match: version `0.2.0` is tag `v0.2.0`.
- Published files are immutable. A failed release is repaired with a new
  version; an existing version is never overwritten.

The Trusted Publisher identity is exact:

- PyPI project: `evidence-loop-visibility-engine`
- GitHub owner: `NavidBroumandfar`
- GitHub repository: `evidence-loop-visibility-engine`
- Workflow: `publish-pypi.yml`
- Environment: `pypi`

## Maintainer checklist

1. Confirm `main` is clean, synchronized, and green.
2. Confirm the changelog, package version, citation version, and tag agree.
3. Run `make check` and `python scripts/artifact_smoke.py` locally.
4. Confirm the pending or existing PyPI Trusted Publisher matches the identity
   above exactly.
5. Verify the GitHub `pypi` environment still has the required `v*` deployment
   policy and maintainer review.
6. Publish the matching GitHub release and approve the protected `pypi`
   deployment after reviewing the build job.
7. Verify the package page and install the published version in a clean
   environment.

This workflow publishes only the offline public package. It does not run a
provider adapter, access a website, or grant authority to mutate an external
system.
