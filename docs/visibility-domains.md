# Visibility domains

The router exposes these versioned modules:

| Domain | Deterministic public plan | Maturity |
| --- | --- | --- |
| measurement-integrity | Preserve source, window, completeness, freshness, uncertainty | Implemented |
| technical-seo | Review bounded indexability/crawlability signals | Implemented |
| search-intent-content | Clarify an answer-oriented intent hypothesis | Implemented |
| aeo-answerability | Review question/answer structure | Implemented |
| geo-citation-research | Observe a citation surface; never produce a GEO score | Synthetic |
| llmo-sampling | Specify fixed-prompt observation, variance, terms, and cost gates | Synthetic |
| brand-governance | Review claims and voice consistency | Approval-gated |
| marketing-conversion | Review a measured conversion hypothesis | Approval-gated |

An unknown domain is not dynamically imported; it blocks only its site lane.
Future model execution, if ever added, must be a separately approved adapter
with explicit calibration, variance, cost, and privacy evidence.
