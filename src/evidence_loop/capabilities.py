"""Versioned, allowlisted deterministic capability routing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    key: str
    version: str
    maturity: str
    plan: str


CAPABILITIES: dict[str, Capability] = {
    "measurement-integrity": Capability("measurement-integrity", "1.0", "implemented-deterministic", "preserve source, window, completeness, freshness, and uncertainty"),
    "technical-seo": Capability("technical-seo", "1.0", "implemented-deterministic", "propose a bounded indexability or crawlability check"),
    "search-intent-content": Capability("search-intent-content", "1.0", "implemented-deterministic", "propose an answer-oriented intent clarification"),
    "aeo-answerability": Capability("aeo-answerability", "1.0", "implemented-deterministic", "propose a clear question-and-answer structure review"),
    "geo-citation-research": Capability("geo-citation-research", "1.0", "synthetic-observation", "propose a citation-surface observation with no GEO score"),
    "llmo-sampling": Capability("llmo-sampling", "1.0", "synthetic-observation", "propose a fixed-prompt observational sample with variance terms"),
    "brand-governance": Capability("brand-governance", "1.0", "approval-gated", "propose a claim and voice consistency review"),
    "marketing-conversion": Capability("marketing-conversion", "1.0", "approval-gated", "propose a measured conversion hypothesis review"),
}


def route(domain: str) -> Capability | None:
    """Return only an explicitly allowlisted capability; never load plugins."""
    return CAPABILITIES.get(domain)


def catalog() -> list[dict[str, str]]:
    return [
        {"key": item.key, "version": item.version, "maturity": item.maturity}
        for item in CAPABILITIES.values()
    ]
