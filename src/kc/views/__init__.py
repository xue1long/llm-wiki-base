"""KC Views package (路线 v2.2 §A-7 / Z-7, spec §12.4 R-7).

Renders Wiki content from Core (KnowledgeObject + Conflict + Evidence)
via the Query + Template compile path — never by per-source summary
generation. The package surface:

    WikiTemplate        — stable, spec-mandated section ordering
    WikiView            — compiled view dataclass (spec §12.4 schema)
    WikiTemplateCompiler— query + template → WikiView

Legacy 1-page-per-source projection is preserved in ``src/wiki/projection.py``
(unchanged) and is NOT the Wiki v2 path.
"""
