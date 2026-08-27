"""Knowledge Core backup + restore (C-0.5a / Z-1).

spec §1 M-7: Knowledge Core is source-of-truth for all ko_* knowledge units;
delete-after-blob-store guarantee means the Core must be independently
backed up and versioned, since knowledge output views cannot be trusted to
reproduce it.

Public surface:
    create_snapshot(paths, objects=...) -> Snapshot
    restore_snapshot(snapshot_id, paths, modified_objects=...) -> bool

Storage layout (.llm-wiki/backups/<snapshot_id>/):
    snapshot.json          — {identity_key: serialized KnowledgeObject}
    identity_keys.txt      — newline-sorted list of identity keys
    version_events.jsonl   — copy of .index/knowledge_graph/events.jsonl
    MANIFEST.yaml          — metadata + before_hash/after_hash (spec §5.13)
"""
