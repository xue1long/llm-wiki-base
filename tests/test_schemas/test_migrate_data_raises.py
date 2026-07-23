# ruflo-kb/tests/test_schemas/test_migrate_data_raises.py
"""Verify the legacy migrate_data() stub raises NotImplementedError.

migrate_data was a no-op shim that returned data unchanged; this silently
corrupted data when callers used it instead of the file-based Migration API.
The fix: raise NotImplementedError pointing callers at the right API.
"""
import pytest

from src.schemas.registry import migrate_data
from src.schemas.migration import SchemaVersion


def test_migrate_data_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        migrate_data({"any": "data"})


def test_migrate_data_with_target_version_raises():
    with pytest.raises(NotImplementedError):
        migrate_data({"any": "data"}, target=SchemaVersion.V2_2)
