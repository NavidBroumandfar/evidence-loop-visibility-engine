# Evidence Loop Visibility Engine public-repository agreement

This is a standalone Apache-2.0 public reference implementation. Keep runtime
behavior synthetic/offline, standard-library-only, deterministic, and
fail-closed for Python 3.10+.

## Hard boundaries

- Never add credentials, private data, private absolute paths, provider state,
  social drafts, or website mutations.
- Do not copy from, import from, symlink to, or depend on private repositories.
- The installed engine and CLI must not use network, browser, provider,
  subprocess, environment credentials, publication, or site writers.
- Release tooling may invoke local Git only to enumerate tracked files; it is
  separate from installed runtime behavior.
- Fixtures use reserved example domains and remain synthetic.
- Never claim rankings, traffic, answer inclusion, citation, causality,
  autonomous SEO, or special `llms.txt`/markup effects.

## Source ownership

- `schema.py`: exact raw-byte parsing, finite JSON, input/path/string safety.
- `engine.py`: Observe -> Choose -> proposal -> Verify -> Record and atomic
  receipts.
- `capabilities.py`: versioned allowlist and deterministic proposal templates.
- `cli.py`: commands, packaged resources, and value-free summaries.
- `action_runner.py` and `action.yml`: repository-relative sanitized
  envelope intake, explicit UTC normalization, one core cycle, fixed safe
  workflow outputs, and approved artifact upload. They never invoke a
  connector or read credential environment variables.
- `scripts/validate_public_release.py`: defense-in-depth release heuristic.
- `docs/public-claims.md`: approved claim boundary.
- `docs/connector-contract.md`: versioned clean-room connector envelope
  semantics and security invariants. The `0.3.0` release candidate was
  controller-accepted on 2026-07-20 after independent read-only
  `opencode-go/grok-4.5` (`high`) evaluation returned PASS. It remains
  unreleased and unpublished until the external release gates pass.
  Connectors remain separately distributed.
- `ROADMAP.md`: status truth for the controller-accepted Phase 1 release
  candidate, separately distributed Phase 2 connector release, and Phase 3
  companion Action candidate. The connector has a bounded live compatibility
  proof; the Action still requires hosted GitHub execution validation. Update
  only when phase status materially changes.

## Required checks

From a fresh checkout, run editable install, full unittest discovery,
`compileall`, the release scanner, validate/run/demo/benchmark, and wheel/sdist
artifact smoke. Confirm that installed artifacts—not the source checkout—can
run all CLI commands and the Action-equivalent runner. Validate `action.yml`
syntax and pinning, then run `tests.test_action`. For the artifact gate, use
`.venv/bin/pip install -e '.[release]'` followed by
`.venv/bin/python scripts/artifact_smoke.py`. Use `make check` for the routine
local gate.

## Release authority

This repository does not self-authorize publication, deployment, GitHub
changes, provider access, or credentials. A controller must review the staged
tree, claims, tests, artifact installs, and exact fingerprint before any
external release action.
