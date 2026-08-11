"""Test ProvenanceTracker (Task 2.4)."""
import json
import tempfile
from pathlib import Path

import pytest

from src.knowledge.provenance import ProvenanceTracker
from src.wiki.core.paths import WikiPaths


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_root():
    """Create a temporary project root with the .index/ directory."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".index").mkdir(parents=True, exist_ok=True)
        yield root


@pytest.fixture
def wiki_paths(temp_root):
    """Return a WikiPaths object rooted at the temporary directory."""
    return WikiPaths(root=temp_root)


@pytest.fixture
def tracker(wiki_paths):
    """Return a fresh ProvenanceTracker backed by the temp wiki paths."""
    return ProvenanceTracker(wiki_paths)


# ---------------------------------------------------------------------------
# Tests — record_derivation
# ---------------------------------------------------------------------------

class TestRecordDerivation:
    """record_derivation records source → object relationships."""

    def test_record_and_retrieve(self, tracker):
        """After recording a derivation, get_derived_objects returns it."""
        tracker.record_derivation("data/a.pdf", "obj-1")
        assert tracker.get_derived_objects("data/a.pdf") == ["obj-1"]

    def test_multiple_objects_from_same_source(self, tracker):
        """Multiple objects derived from the same source are all returned."""
        tracker.record_derivation("data/a.pdf", "obj-1")
        tracker.record_derivation("data/a.pdf", "obj-2")
        tracker.record_derivation("data/a.pdf", "obj-3")
        derived = tracker.get_derived_objects("data/a.pdf")
        assert sorted(derived) == ["obj-1", "obj-2", "obj-3"]

    def test_idempotent(self, tracker):
        """Recording the same derivation twice does not duplicate the entry."""
        tracker.record_derivation("data/a.pdf", "obj-1")
        tracker.record_derivation("data/a.pdf", "obj-1")
        derived = tracker.get_derived_objects("data/a.pdf")
        assert derived == ["obj-1"]

    def test_unknown_source_returns_empty_list(self, tracker):
        """Querying an unknown source returns an empty list."""
        assert tracker.get_derived_objects("nonexistent.pdf") == []


# ---------------------------------------------------------------------------
# Tests — get_derived_objects
# ---------------------------------------------------------------------------

class TestGetDerivedObjects:
    """get_derived_objects returns all objects derived from a source."""

    def test_empty_for_new_tracker(self, tracker):
        """A fresh tracker returns an empty list for any source."""
        assert tracker.get_derived_objects("anything.pdf") == []

    def test_preserves_order_of_recording(self, tracker):
        """Derived objects are returned in the order they were recorded."""
        tracker.record_derivation("data/a.pdf", "third")
        tracker.record_derivation("data/a.pdf", "first")
        tracker.record_derivation("data/a.pdf", "second")
        # Order should match insertion order
        assert tracker.get_derived_objects("data/a.pdf") == ["third", "first", "second"]


# ---------------------------------------------------------------------------
# Tests — get_provenance_chain
# ---------------------------------------------------------------------------

class TestGetProvenanceChain:
    """get_provenance_chain returns the full chain for an object."""

    def test_returns_chain_for_known_object(self, tracker):
        """All chain fields are populated for a known object."""
        tracker.record_derivation("docs/report.pdf", "claim-42")
        chain = tracker.get_provenance_chain("claim-42")
        assert chain["source_path"] == "docs/report.pdf"
        assert chain["derived_from"] == "docs/report.pdf"
        assert chain["source_status"] == "active"
        assert "claim-42" in chain["derived_objects"]

    def test_returns_empty_dict_for_unknown_object(self, tracker):
        """Unknown objects return an empty dict."""
        chain = tracker.get_provenance_chain("nonexistent")
        assert chain == {}

    def test_derived_objects_in_chain_includes_siblings(self, tracker):
        """The derived_objects in the chain includes all objects from that source."""
        tracker.record_derivation("data/x.pdf", "child-1")
        tracker.record_derivation("data/x.pdf", "child-2")
        chain = tracker.get_provenance_chain("child-1")
        assert sorted(chain["derived_objects"]) == ["child-1", "child-2"]


# ---------------------------------------------------------------------------
# Tests — mark_source_deleted
# ---------------------------------------------------------------------------

class TestMarkSourceDeleted:
    """mark_source_deleted preserves the chain but sets source_status to deleted."""

    def test_marks_source_as_deleted(self, tracker):
        """After mark_source_deleted, source_status changes to 'deleted'."""
        tracker.record_derivation("data/old.pdf", "obj-x")
        tracker.mark_source_deleted("data/old.pdf")
        chain = tracker.get_provenance_chain("obj-x")
        assert chain["source_status"] == "deleted"

    def test_derived_objects_still_retrievable(self, tracker):
        """Derived objects are still retrievable after source is marked deleted."""
        tracker.record_derivation("data/old.pdf", "obj-x")
        tracker.mark_source_deleted("data/old.pdf")
        derived = tracker.get_derived_objects("data/old.pdf")
        assert derived == ["obj-x"]

    def test_no_op_for_unknown_source(self, tracker):
        """mark_source_deleted on an unknown source does not crash."""
        tracker.mark_source_deleted("nonexistent.pdf")
        # Should not raise and should not create a phantom entry
        assert tracker.get_derived_objects("nonexistent.pdf") == []

    def test_preserves_provenance_chain_after_deletion(self, tracker):
        """The full chain (including derived_from) is intact after mark_source_deleted."""
        tracker.record_derivation("data/old.pdf", "obj-z")
        tracker.record_derivation("data/old.pdf", "obj-y")
        tracker.mark_source_deleted("data/old.pdf")

        chain_z = tracker.get_provenance_chain("obj-z")
        assert chain_z["derived_from"] == "data/old.pdf"
        assert chain_z["source_status"] == "deleted"
        assert "obj-z" in chain_z["derived_objects"]
        assert "obj-y" in chain_z["derived_objects"]


# ---------------------------------------------------------------------------
# Tests — source_status default
# ---------------------------------------------------------------------------

class TestSourceStatusDefault:
    """New derivations have source_status='active' by default."""

    def test_new_source_is_active(self, tracker):
        """A newly recorded source has source_status='active'."""
        tracker.record_derivation("data/fresh.pdf", "obj-new")
        chain = tracker.get_provenance_chain("obj-new")
        assert chain["source_status"] == "active"

    def test_active_persists_after_multiple_derivations(self, tracker):
        """source_status stays 'active' after adding more derivations."""
        tracker.record_derivation("data/fresh.pdf", "obj-a")
        tracker.record_derivation("data/fresh.pdf", "obj-b")
        chain = tracker.get_provenance_chain("obj-a")
        assert chain["source_status"] == "active"


# ---------------------------------------------------------------------------
# Tests — multiple sources
# ---------------------------------------------------------------------------

class TestMultipleSources:
    """Derivations from different sources do not mix."""

    def test_sources_are_independent(self, tracker):
        """Each source maintains its own list of derived objects."""
        tracker.record_derivation("a.pdf", "from-a-1")
        tracker.record_derivation("a.pdf", "from-a-2")
        tracker.record_derivation("b.pdf", "from-b-1")

        assert sorted(tracker.get_derived_objects("a.pdf")) == ["from-a-1", "from-a-2"]
        assert tracker.get_derived_objects("b.pdf") == ["from-b-1"]

    def test_delete_one_source_does_not_affect_others(self, tracker):
        """Marking one source as deleted does not touch others."""
        tracker.record_derivation("active.pdf", "obj-a")
        tracker.record_derivation("deleted.pdf", "obj-d")

        tracker.mark_source_deleted("deleted.pdf")

        chain_active = tracker.get_provenance_chain("obj-a")
        assert chain_active["source_status"] == "active"

        chain_deleted = tracker.get_provenance_chain("obj-d")
        assert chain_deleted["source_status"] == "deleted"


# ---------------------------------------------------------------------------
# Tests — persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    """Data survives across ProvenanceTracker instances pointing at the same store."""

    def test_data_survives_reload(self, temp_root, wiki_paths):
        """Data recorded by one tracker is visible to a new tracker with the same paths."""
        t1 = ProvenanceTracker(wiki_paths)
        t1.record_derivation("data/persist.pdf", "obj-p")
        t1.record_derivation("data/persist.pdf", "obj-q")

        # Create a new tracker pointing at the same store
        t2 = ProvenanceTracker(wiki_paths)
        assert sorted(t2.get_derived_objects("data/persist.pdf")) == ["obj-p", "obj-q"]

        chain = t2.get_provenance_chain("obj-p")
        assert chain["derived_from"] == "data/persist.pdf"
        assert chain["source_status"] == "active"

    def test_deleted_status_persists(self, temp_root, wiki_paths):
        """A source marked deleted stays deleted after reload."""
        t1 = ProvenanceTracker(wiki_paths)
        t1.record_derivation("data/to_delete.pdf", "obj-x")
        t1.mark_source_deleted("data/to_delete.pdf")

        t2 = ProvenanceTracker(wiki_paths)
        chain = t2.get_provenance_chain("obj-x")
        assert chain["source_status"] == "deleted"

    def test_file_is_created_on_first_save(self, wiki_paths):
        """The provenance.json file is created after the first derivation."""
        store_path = Path(wiki_paths.index) / "provenance.json"
        assert not store_path.exists()

        tracker = ProvenanceTracker(wiki_paths)
        tracker.record_derivation("data/new.pdf", "obj-1")

        assert store_path.exists()
        data = json.loads(store_path.read_text(encoding="utf-8"))
        assert "_sources" in data
        assert "data/new.pdf" in data["_sources"]


# ---------------------------------------------------------------------------
# Tests — reverse lookup
# ---------------------------------------------------------------------------

class TestObjectSourcesReverseLookup:
    """The reverse index allows looking up an object's source."""

    def test_reverse_lookup_via_provenance_chain(self, tracker):
        """provenance_chain for an object shows its derived_from source."""
        tracker.record_derivation("source/doc.pdf", "entity-1")
        chain = tracker.get_provenance_chain("entity-1")
        assert chain["derived_from"] == "source/doc.pdf"

    def test_reverse_lookup_independent_of_order(self, tracker):
        """Recording objects in any order still resolves the correct source."""
        tracker.record_derivation("s1.pdf", "o1")
        tracker.record_derivation("s2.pdf", "o2")
        tracker.record_derivation("s1.pdf", "o3")

        assert tracker.get_provenance_chain("o1")["derived_from"] == "s1.pdf"
        assert tracker.get_provenance_chain("o2")["derived_from"] == "s2.pdf"
        assert tracker.get_provenance_chain("o3")["derived_from"] == "s1.pdf"

    def test_object_can_only_have_one_source(self, tracker):
        """An object ID maps to the first source it was recorded with."""
        tracker.record_derivation("first.pdf", "shared-obj")
        tracker.record_derivation("second.pdf", "shared-obj")
        # The reverse index keeps the first mapping
        chain = tracker.get_provenance_chain("shared-obj")
        assert chain["derived_from"] == "first.pdf"


# ---------------------------------------------------------------------------
# Tests — page info
# ---------------------------------------------------------------------------

class TestRecordDerivationWithPageInfo:
    """Source paths may include page references like 'a.pdf#page=23'."""

    def test_page_fragment_in_source_path(self, tracker):
        """Source paths with #page= fragments are stored as-is."""
        tracker.record_derivation("data/doc.pdf#page=23", "claim-page23")
        derived = tracker.get_derived_objects("data/doc.pdf#page=23")
        assert derived == ["claim-page23"]

    def test_multiple_pages_in_source_paths(self, tracker):
        """Different pages from the same document are tracked separately."""
        tracker.record_derivation("data/doc.pdf#page=1", "claim-p1")
        tracker.record_derivation("data/doc.pdf#page=5", "claim-p5")

        assert tracker.get_derived_objects("data/doc.pdf#page=1") == ["claim-p1"]
        assert tracker.get_derived_objects("data/doc.pdf#page=5") == ["claim-p5"]

    def test_provenance_chain_includes_page_info(self, tracker):
        """The provenance chain preserves page fragment information."""
        tracker.record_derivation("data/doc.pdf#page=42", "claim-with-page")
        chain = tracker.get_provenance_chain("claim-with-page")
        assert chain["source_path"] == "data/doc.pdf#page=42"
        assert chain["derived_from"] == "data/doc.pdf#page=42"
