# Loop Engineering

This project uses Loop Engineering as a bounded evidence feedback pattern:

1. **Observe**: accept a timestamped evidence packet with source kind,
   completeness, freshness, and uncertainty.
2. **Choose**: require fresh, non-missing evidence and choose the lowest numeric
   priority, then the stable opportunity ID as a tie-breaker.
3. **Act**: create exactly one proposal per site. No website or content is
   changed.
4. **Verify**: independently reconstruct the selected opportunity and routed
   capability; require exact evidence IDs, approval gate, `approval_required`
   as the boolean `true`, and `mutation_allowed` as the boolean `false`.
5. **Record**: write a digest-bearing receipt atomically and retain the last
   successful receipt.
6. **Repeat or stop**: stop at `approval-required`, `clean-no-op`, or
   `blocked`. Globally, accepted proposals take precedence; otherwise any
   blocked lane makes the run `blocked`, including a clean-no-op plus blocked
   combination. Accepted and blocked lanes together remain `approval-required`
   so independent accepted sites are not contaminated.

Fresh evidence can change the next choice: a high-priority opportunity backed
by stale evidence is ineligible, while a lower-priority fresh opportunity can
be proposed. This is a deterministic policy, not a prediction of traffic,
rankings, answers, or citations.
