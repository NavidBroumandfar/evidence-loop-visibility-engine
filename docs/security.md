# Security model

The installed engine and CLI are offline and synthetic by default. They do not
read environment credentials, open a network connection, invoke a browser or
provider, spawn a process, mutate a site, or publish content. The release
scanner is separate defense-in-depth tooling and does invoke local Git to
enumerate tracked release files; that process is not part of installed runtime.

Input safeguards include strict UTF-8 JSON, duplicate-key rejection, a 1 MiB
inclusive byte limit, bounded nesting/arrays/text, safe identifiers and UTC
timestamps, reserved example hosts, per-site uniqueness and evidence lineage,
and detection of private paths, credential/token markers, token-shaped digests,
and wrapped markers. Private absolute paths are detected regardless of adjacent
punctuation, including common POSIX account/system roots and Windows drive or
UNC account/system paths. Windows drive paths accept forward-slash or
backslash separators, including redundant separators; UNC paths accept either
separator and an optional share component. Ordinary public URLs and ordinary
text are not themselves path markers. Named opaque underscore-prefixed
provider/private identifiers, canonical UUID-shaped values, and file URI
paths are rejected. Human aliases such as `team-plan`, `project-plan`,
`properties-summary`, and `public-alpha` remain valid. Exact named digest
fields remain separately validated rather than being treated as token text.

The `normalize` command requires an explicit UTC `--as-of` bound. It rejects
more than the public input-count limit before loading any envelope, stops
loading as soon as cumulative raw bytes exceed 1 MiB, and leaves an existing
normalized output untouched on those failures. Output paths reject lexical
traversal and symlink ancestors/children. Receipt writes use a temporary file
plus atomic replace; the previous `last-success.json` remains if writing fails.

This is not a sandbox for untrusted code. Keep adapters and any future live
integration in a separate, reviewed process with its own credentials and
approval gates.

The local Phase 3 companion Action adds a fail-closed file orchestration
boundary without adding provider access. It accepts only safe
repository-relative directory components. The envelope directory must exist
and contain one to 200 direct regular `.json` children with bounded safe
names; symlinks, subdirectories, other files, traversal, absolute caller
paths, and aggregate input beyond 1 MiB are rejected. The output directory
must be new, repository-relative, non-overlapping, and free of symlink
ancestors. The runner validates GitHub output metadata under the supplied
runner-temp directory before it reads envelopes or creates artifacts.
It rechecks the cumulative limit from the exact bytes read, verifies canonical
normalized/receipt digests, and requires exact preservation of each named
provider-response digest. Raw provider-response bytes never enter this Action,
so recomputing that connector-owned digest is outside its authority boundary.

The Action does not accept token, credential, provider-ID, command, shell, or
connector inputs. It does not enumerate environment variables or invoke a
provider connector. Caller workflows must not pass provider credentials into
the Action step. External `setup-python` and `upload-artifact` actions are
pinned to full commit SHAs, shell commands consume expressions only through
quoted environment variables, package-index access is disabled for core
installation, and the documented job permission is `contents: read`.
GitHub's artifact service is workflow infrastructure, not a provider request
by the evidence-loop runtime.
