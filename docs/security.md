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
and wrapped markers. Output paths reject lexical traversal and symlink
ancestors/children. Receipt writes use a temporary file plus atomic replace;
the previous `last-success.json` remains if writing fails.

This is not a sandbox for untrusted code. Keep adapters and any future live
integration in a separate, reviewed process with its own credentials and
approval gates.
