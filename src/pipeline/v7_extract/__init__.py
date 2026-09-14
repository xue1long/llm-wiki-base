"""V7.1.1 extract pipeline (RFC v6, plan 2026-09-13).

This subpackage implements the 7-stage extraction pipeline for raw source
files. It is intentionally separate from the existing
``src.pipeline.stages`` (Collector / Analyzer / Generator) so the legacy
pipeline keeps running unchanged while V7 extract evolves.

Stages:
  1. doc_classifier          → classify_doc(content) -> DocType
  2. structure_recognizer    → extract_structure(content, doc_type) -> Structure
  3. completeness_checker    → check_completeness(content, doc_type) -> (bool, str)
  4. topic_clusterer         → cluster_topics(items) -> list[Topic]
  5. slot_filler             → fill_slots(topic, template) -> ConceptPage
  6. relation_extractor      → extract_relations(pages) -> Relations
  7. wiki_writer             → commit_and_index(pages, relations)

All LLM calls go through LLMClient (this file) so the pipeline can be
unit-tested with a fake LLM (M9-V5 fix).
"""