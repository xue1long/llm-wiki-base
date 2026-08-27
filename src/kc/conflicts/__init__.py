"""Conflict Classifier (A-3 / G6, spec §8.2 + §5.11 Conflict).

Classifies a pair of statements into one of the 6 conflict types defined in
spec §8.2: actual / conditional / temporal / perspective / none / unresolved.

Maps directly to the 10 gold cases in ``docs/evaluation/cases/conflict.yaml``
(C-3.2 deliverable). Used by the resolution layer to pick the right action
(supersede / link / dispute / quarantine) per spec §11.4.
"""
from .classifier import Conflict, ConflictClassifier, ConflictType

__all__ = ["Conflict", "ConflictClassifier", "ConflictType"]