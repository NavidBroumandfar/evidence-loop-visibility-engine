# Saved loop

## Fresh evidence -> one safe proposal

- **Intent**: make one evidence-backed visibility decision per site.
- **Trigger**: a new synthetic evidence packet is available.
- **Observe**: validate source kind, UTC timestamp, completeness, freshness,
  uncertainty, site, and evidence IDs.
- **Choose**: select the lowest priority fresh opportunity with complete or
  partial evidence; break ties by opportunity ID.
- **Act**: draft one capability plan with `approval_required=true` and no site
  mutation.
- **Verify**: check opportunity-to-evidence lineage and the human approval gate.
- **Record**: atomically write `run.json`; update `last-success.json` only for a
  non-blocked terminal state.
- **Repeat/stop**: `approval-required` waits for a human; `clean-no-op` waits
  for fresh evidence; `blocked` waits for correction.

This compact loop is a public example of a bounded feedback method, not a claim
of authorship or a promise of search outcomes.
