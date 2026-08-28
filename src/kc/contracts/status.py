"""Small publication state contract for the first vertical slice."""

from enum import StrEnum


class PublicationState(StrEnum):
    CANDIDATE = "candidate"
    STRUCTURALLY_VERIFIED = "structurally_verified"
    # Legacy read-compatibility value; never emit for new records.
    VERIFIED = "verified"
    PUBLISHED = "published"
    QUARANTINED = "quarantined"


def can_publish(state: PublicationState) -> bool:
    """Return whether verification has passed enough to allow projection."""
    return state is PublicationState.STRUCTURALLY_VERIFIED
