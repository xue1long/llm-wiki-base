"""ResearcherAgent — cross-source deep research agent.

Input: research question
Output: ResearchReport (becomes synthesis-type KnowledgeObject)

Safety measures (per audit M7):
1. Web search results tagged provenance.source_type = "web_search"
   with search URL and retrieval timestamp
2. Synthesis output lifecycle defaults to PROCESSING (NOT auto-ACTIVE)
3. Synthesis content must pass Reviewer gate before ACTIVE
4. Domain whitelist filtering on Tavily results

Difference from Analyzer:
- Researcher: cross-source synthesis -> synthesis type
- Analyzer: single-source extraction -> candidates/claims
"""

import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlparse

from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
)


@dataclass
class ResearchReport:
    """Output of the Researcher agent — a synthesis-type KnowledgeObject candidate."""

    id: str                           # Generated ID
    question: str                     # The research question
    summary: str                      # Synthesized answer
    sources: list[dict]               # Source information from web search
    confidence: float                 # Overall confidence
    claims: list[dict]                # Extracted claims with evidence
    created_at: int                   # Unix ms


class ResearcherAgent:
    """Cross-source deep research agent.

    Input: research question
    Output: ResearchReport (becomes synthesis-type KnowledgeObject)

    Safety measures (per audit M7):
    1. Web search results tagged provenance.source_type = "web_search"
       with search URL and retrieval timestamp
    2. Synthesis output lifecycle defaults to PROCESSING (NOT auto-ACTIVE)
    3. Synthesis content must pass Reviewer gate before ACTIVE
    4. Domain whitelist filtering on Tavily results

    Difference from Analyzer:
    - Researcher: cross-source synthesis -> synthesis type
    - Analyzer: single-source extraction -> candidates/claims
    """

    def __init__(self, web_search_provider=None, provenance_tracker=None,
                 allowed_domains: list[str] | None = None):
        self._search = web_search_provider
        self._provenance = provenance_tracker
        # None = allow all (per plan spec: None is safe default, not blocking)
        self._allowed_domains = allowed_domains

    async def research(self, question: str, depth: int = 3) -> ResearchReport:
        """Conduct deep research on a question.

        1. Web search for the question
        2. Fetch and extract top results
        3. Synthesize findings into a ResearchReport
        4. Tag all sources with provenance.source_type="web_search"
        5. Return report (does NOT auto-promote to ACTIVE)
        """
        report_id = f"research-{uuid.uuid4().hex[:12]}"
        retrieved_at = int(time.time() * 1000)

        # 1-2. Web search (or graceful degradation)
        if self._search is not None:
            try:
                raw_results = await self._search.search(question, top_k=depth * 5)
            except Exception:
                raw_results = []
        else:
            raw_results = []

        # 3. Filter by domain whitelist
        filtered_results = self._filter_by_domain(raw_results)

        # 4. Tag each result with web search provenance metadata
        tagged_sources = []
        for r in filtered_results:
            tagged = dict(r)
            tagged["source_type"] = "web_search"
            tagged["search_url"] = r.get("url", "")
            tagged["retrieved_at"] = retrieved_at
            tagged_sources.append(tagged)

        # 5. Synthesize findings
        report = self._synthesize(question, tagged_sources)
        report.id = report_id
        report.created_at = retrieved_at

        return report

    def _filter_by_domain(self, results: list[dict]) -> list[dict]:
        """Filter search results by allowed_domains whitelist.

        If allowed_domains is None or empty, allow all.
        If whitelist is set, only return results matching allowed domains.
        """
        if not self._allowed_domains:
            return results

        filtered = []
        for r in results:
            url = r.get("url", "")
            domain = self._extract_domain(url)
            if self._is_domain_allowed(domain):
                filtered.append(r)
        return filtered

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL for whitelist checking."""
        if not url:
            return ""
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        return hostname

    def _is_domain_allowed(self, domain: str) -> bool:
        """Check if domain matches the allowed_domains whitelist.

        A domain is allowed if it ends with any entry in allowed_domains.
        E.g., domain="sub.example.com" matches allowed_domains=["example.com"].
        """
        if not self._allowed_domains:
            return True
        domain_lower = domain.lower()
        for allowed in self._allowed_domains:
            allowed_lower = allowed.lower().rstrip("/")
            if domain_lower == allowed_lower or domain_lower.endswith("." + allowed_lower):
                return True
        return False

    def _synthesize(self, question: str, sources: list[dict]) -> ResearchReport:
        """Synthesize research findings into a structured report.

        Creates a ResearchReport with:
        - Summary of findings
        - Source list with provenance metadata
        - Extracted claims (basic: key facts from each source)
        - Confidence based on source count and quality
        """
        if not sources:
            return ResearchReport(
                id="",
                question=question,
                summary="",
                sources=[],
                confidence=0.3,
                claims=[],
                created_at=int(time.time() * 1000),
            )

        # Summary: concatenate top result snippets
        snippets = []
        for i, s in enumerate(sources):
            snippet = s.get("snippet", "") or s.get("content", "")
            title = s.get("title", "")
            url = s.get("url", "")
            if snippet:
                snippets.append(f"[{i+1}] {title}: {snippet}")
            elif title:
                snippets.append(f"[{i+1}] {title} ({url})")

        summary = "\n\n".join(snippets)

        # Claims: extract key sentences from each source
        claims = []
        for i, s in enumerate(sources):
            snippet = s.get("snippet", "") or s.get("content", "")
            if snippet:
                # Split into sentences and take the first meaningful one as a claim
                sentences = [sent.strip() for sent in snippet.replace("\n", " ").split(".") if sent.strip()]
                for sentence in sentences[:2]:  # Max 2 claims per source
                    claims.append({
                        "text": sentence + ".",
                        "source_index": i,
                        "source_url": s.get("url", ""),
                        "source_title": s.get("title", ""),
                    })

        # Confidence: base + per-source bonus, capped at 1.0
        confidence = min(1.0, 0.3 + len(sources) * 0.1)

        return ResearchReport(
            id="",
            question=question,
            summary=summary,
            sources=sources,
            confidence=confidence,
            claims=claims,
            created_at=int(time.time() * 1000),
        )

    def create_knowledge_object(self, report: ResearchReport) -> KnowledgeObject:
        """Convert ResearchReport to a KnowledgeObject(type=synthesis).

        Lifecycle is PROCESSING (not ACTIVE) — Reviewer gate required.
        Provenance source_type = "web_search".
        """
        now_ms = int(time.time() * 1000)

        # Build provenance entries for each source
        provenance_list = []
        for s in report.sources:
            prov = Provenance(
                source_path=s.get("url", ""),
                page=None,
                quote=s.get("snippet", "") or s.get("content", ""),
                ingested_at=s.get("retrieved_at", now_ms),
                ingestor_version="web_search",
            )
            provenance_list.append(prov)

        # Use the first provenance as primary; store extras in a
        # _web_sources attribute for downstream consumers.
        primary_provenance = provenance_list[0] if provenance_list else Provenance(
            source_path="",
            page=None,
            quote="",
            ingested_at=now_ms,
            ingestor_version="web_search",
        )

        content = f"# {report.question}\n\n{report.summary}\n"
        if report.claims:
            content += "\n## Claims\n\n"
            for i, claim in enumerate(report.claims):
                content += f"- [{claim.get('source_index', '?')}] {claim.get('text', '')}\n"

        obj = KnowledgeObject(
            id=report.id,
            type=KnowledgeType.SYNTHESIS,
            title=report.question,
            content=content,
            lifecycle=LifecycleState.PROCESSING,
            confidence=report.confidence,
            provenance=primary_provenance,
            created_at=report.created_at,
            updated_at=now_ms,
        )

        # Store all web sources as additional metadata via the relations field
        # so they survive round-tripping.
        obj.relations = [
            {
                "source_type": s.get("source_type", "web_search"),
                "url": s.get("url", ""),
                "title": s.get("title", ""),
                "retrieved_at": s.get("retrieved_at", now_ms),
            }
            for s in report.sources
        ]

        # Record provenance tracking if available
        if self._provenance is not None:
            for s in report.sources:
                url = s.get("url", "")
                if url:
                    try:
                        self._provenance.record_derivation(url, report.id)
                    except Exception:
                        pass

        return obj
